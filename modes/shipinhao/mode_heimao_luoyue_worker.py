import argparse
import json
import logging
import os
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from app._random_frame_swap_core import filter_graph, shuffled_order, special_offsets
except ImportError:
    # 发布版必须用受保护的 .pyd。若退到明文等价实现，等于删掉一个文件就能绕开
    # VMProtect —— 所以 frozen 下直接失败，只在源码树里保留明文回退方便调试。
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        raise RuntimeError("发布版缺少或无法加载受保护的爆闪算法核心")
    from modes.shipinhao.heimao_luoyue_core import filter_graph, shuffled_order, special_offsets


WIDTH, HEIGHT, FPS, PRESENTATION_FPS = 720, 1280, 30, 60
FRAME_SIZE = WIDTH * HEIGHT * 3 // 2
TIMESCALE, STTS_DELTA = 15360, 512
THREADS, VIDEO_BITRATE_K = 12, 10000
CACHE_WORKERS = min(6, max(2, (os.cpu_count() or 4) // 2))
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
LOGGER = logging.getLogger("spark.processor")


def run_json(command, label):
    LOGGER.info("%s: %s", label, subprocess.list2cmdline([str(part) for part in command]))
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    except OSError as error:
        raise RuntimeError(f"{label} could not start: {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        LOGGER.error("%s failed with exit code %s: %s", label, result.returncode, detail)
        raise RuntimeError(f"{label} failed (exit {result.returncode}): {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        LOGGER.error("%s returned invalid JSON: %s", label, result.stdout[:1000])
        raise RuntimeError(f"{label} returned invalid media information") from error


def frame_stream(pipe):
    while frame := pipe.read(FRAME_SIZE):
        if len(frame) != FRAME_SIZE:
            raise RuntimeError("FFmpeg returned a truncated frame")
        yield frame


def probe_media(ffprobe, input_path, include_frames=False):
    command = [
        ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(input_path)
    ]
    info = run_json(command, f"FFprobe input {input_path}")
    video = next((stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("Input has no video stream")
    durations = (video.get("duration"), info.get("format", {}).get("duration"))
    duration = next((float(value) for value in durations if value not in (None, "N/A") and float(value) > 0), 0)
    if not duration:
        raise RuntimeError("Could not determine input duration")
    audio = any(stream.get("codec_type") == "audio" for stream in info.get("streams", []))
    if not include_frames:
        return duration, audio
    return duration, audio, max(1, round(duration * FPS))


class FrameCache:
    def __init__(self, path):
        self.path = Path(path)
        self.writer = self.path.open("wb")
        self.items = []

    @staticmethod
    def pack(frame):
        compressed = zlib.compress(frame, 1)
        is_compressed = len(compressed) < len(frame)
        return (compressed if is_compressed else frame), is_compressed

    def append_packed(self, packed, is_compressed):
        offset = self.writer.tell()
        self.writer.write(packed)
        self.items.append((offset, len(packed), is_compressed))

    def seal(self):
        self.writer.close()

    def iter_order(self, order, workers=CACHE_WORKERS):
        with self.path.open("rb") as reader, ThreadPoolExecutor(max_workers=workers) as pool:
            pending = deque()
            for index in order:
                offset, size, compressed = self.items[index]
                reader.seek(offset)
                packed = reader.read(size)
                if len(packed) != size:
                    raise RuntimeError("Random frame cache is truncated")
                pending.append(pool.submit(zlib.decompress if compressed else bytes, packed))
                if len(pending) >= workers * 2:
                    yield pending.popleft().result()
            while pending:
                yield pending.popleft().result()


def cache_frames(cache, frames, workers=CACHE_WORKERS, on_frame=None):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = deque()
        written = 0
        for frame in frames:
            pending.append(pool.submit(FrameCache.pack, frame))
            if len(pending) >= workers * 2:
                cache.append_packed(*pending.popleft().result())
                written += 1
                if on_frame:
                    on_frame(written)
        while pending:
            cache.append_packed(*pending.popleft().result())
            written += 1
            if on_frame:
                on_frame(written)


def decode_to_cache(ffmpeg, input_path, cache_path, use_cuda, total_frames=0, on_progress=None):
    scale = f"fps={FPS},scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1,format=yuv420p"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", str(THREADS),
               "-filter_threads", str(THREADS)]
    if use_cuda:
        command += ["-hwaccel", "cuda"]
    command += ["-i", str(input_path), "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", scale,
                "-fps_mode", "passthrough", "-pix_fmt", "yuv420p", "-threads", str(THREADS),
                "-f", "rawvideo", "pipe:1"]
    LOGGER.info("Decode command: %s", subprocess.list2cmdline([str(part) for part in command]))
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=NO_WINDOW)
    except OSError as error:
        raise RuntimeError(f"FFmpeg decoder could not start: {error}") from error
    assert process.stdout is not None
    cache = FrameCache(cache_path)
    try:
        def report(index):
            if on_progress and (index == 1 or index % 15 == 0):
                on_progress(index, total_frames)
        cache_frames(cache, frame_stream(process.stdout), on_frame=report)
    finally:
        process.stdout.close()
        cache.seal()
    assert process.stderr is not None
    error = process.stderr.read().decode("utf-8", "replace").strip()
    if process.wait() or not cache.items:
        (LOGGER.warning if use_cuda else LOGGER.error)(
            "FFmpeg %s decode failed: %s", "CUDA" if use_cuda else "CPU",
            error or "no frames returned")
        raise RuntimeError(error or "Could not decode the input video")
    if on_progress:
        on_progress(len(cache.items), len(cache.items))
    return cache


def create_random_cache(ffmpeg, input_path, cache_path, seed):
    try:
        cache = decode_to_cache(ffmpeg, input_path, cache_path, True)
    except RuntimeError:
        cache = decode_to_cache(ffmpeg, input_path, cache_path, False)
    order = shuffled_order(len(cache.items), seed)
    return cache, order


def select_encoder(ffmpeg, requested):
    if requested != "h264_nvenc":
        LOGGER.info("Encoder selected: CPU libx264")
        return requested
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi",
        "-i", "color=c=black:s=720x1280:r=1:d=0.1", "-frames:v", "1", "-an",
        "-pix_fmt", "yuv420p", "-c:v", "h264_nvenc", "-f", "null", "-",
    ]
    LOGGER.info("NVENC capability check: %s", subprocess.list2cmdline(command))
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=15, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as error:
        LOGGER.warning("NVENC check could not complete; using CPU libx264: %s", error)
        return "libx264"
    if result.returncode == 0:
        LOGGER.info("Encoder selected: NVIDIA NVENC")
        return "h264_nvenc"
    detail = result.stderr.decode("utf-8", "replace").strip()
    LOGGER.warning("NVENC unavailable; using CPU libx264. FFmpeg says: %s",
                   detail or f"exit code {result.returncode}")
    return "libx264"


def encode_interleaved(ffmpeg, input_path, temp_path, duration, has_audio, cache, order, encoder,
                       on_progress=None):
    command = [
        ffmpeg, "-nostdin", "-nostats", "-filter_complex_threads", str(THREADS),
        "-filter_threads", str(THREADS), "-hide_banner", "-loglevel", "warning", "-y",
        "-threads", str(THREADS), "-i", str(input_path), "-f", "rawvideo",
        "-pixel_format", "yuv420p", "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS),
        "-threads", str(THREADS), "-i", "pipe:0", "-filter_complex", filter_graph(),
        "-map", "[vout]",
    ]
    if has_audio:
        command += ["-map", "0:a:0"]
    command += ["-fps_mode:v", "passthrough", "-pix_fmt", "yuv420p", "-profile:v", "main",
                "-g", "18", "-bf", "3", "-video_track_timescale", str(TIMESCALE),
                "-t", f"{duration:.9f}"]
    if has_audio:
        command += ["-af", f"apad=pad_dur={duration:.9f}", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "44100", "-ac", "2"]
    else:
        command += ["-an"]
    command += ["-c:v", encoder]
    if encoder == "h264_nvenc":
        command += ["-preset", "p2", "-tune", "hq", "-rc:v", "vbr", "-b:v", "10000k",
                    "-maxrate:v", "10000k", "-bufsize:v", "20000k", "-spatial-aq", "1",
                    "-temporal-aq", "1"]
    else:
        command += ["-preset", "veryfast", "-b:v", "10000k", "-maxrate:v", "10000k",
                    "-bufsize:v", "20000k", "-x264-params",
                    "keyint=18:min-keyint=18:scenecut=0:bframes=3:ref=3:nal-hrd=vbr", "-threads", "0"]
    command.append(str(temp_path))

    errors = []
    LOGGER.info("Encode command: %s", subprocess.list2cmdline([str(part) for part in command]))
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=NO_WINDOW)
    except OSError as error:
        raise RuntimeError(f"FFmpeg encoder could not start: {error}") from error
    assert process.stdin is not None and process.stderr is not None

    def read_errors():
        errors.append(process.stderr.read().decode("utf-8", "replace"))

    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    write_error = None
    try:
        for index, frame in enumerate(cache.iter_order(order), 1):
            process.stdin.write(frame)
            if on_progress and (index == 1 or index % 15 == 0):
                on_progress(index, len(order))
    except BrokenPipeError as error:
        write_error = error
    finally:
        try:
            process.stdin.close()
        except BrokenPipeError as error:
            write_error = write_error or error
    code = process.wait()
    reader.join()
    if code:
        detail = (errors[0] if errors else str(write_error or "FFmpeg encoding failed")).strip()
        LOGGER.error("FFmpeg encode failed with exit code %s: %s", code, detail)
        raise RuntimeError(detail)
    if write_error:
        LOGGER.info("FFmpeg reached the requested duration and closed the frame input normally")
    if on_progress:
        on_progress(len(order), len(order))


def box_header(data, offset=0, end=None):
    end = len(data) if end is None else end
    if offset + 8 > end:
        raise RuntimeError("Truncated MP4 box header")
    size, kind = struct.unpack_from(">I4s", data, offset)
    header = 8
    if size == 1:
        if offset + 16 > end:
            raise RuntimeError("Truncated MP4 largesize")
        size, header = struct.unpack_from(">Q", data, offset + 8)[0], 16
    elif size == 0:
        size = end - offset
    if size < header or offset + size > end:
        raise RuntimeError(f"Invalid MP4 box {kind!r}")
    return size, kind, header


def iter_boxes(data):
    offset = 0
    while offset < len(data):
        size, kind, header = box_header(data, offset)
        yield kind, data[offset:offset + size], header
        offset += size
    if offset != len(data):
        raise RuntimeError("Invalid MP4 container")


def box_payload(raw):
    _, _, header = box_header(raw)
    return raw[header:]


def make_box(kind, payload):
    size = len(payload) + 8
    if size <= 0xFFFFFFFF:
        return struct.pack(">I4s", size, kind) + payload
    return struct.pack(">I4sQ", 1, kind, len(payload) + 16) + payload


def parse_stts(raw):
    payload = box_payload(raw)
    if len(payload) < 8:
        raise RuntimeError("Invalid stts box")
    count = struct.unpack_from(">I", payload, 4)[0]
    result, offset = [], 8
    for _ in range(count):
        if offset + 8 > len(payload):
            raise RuntimeError("Truncated stts entry")
        samples, delta = struct.unpack_from(">II", payload, offset)
        result.extend([delta] * samples)
        offset += 8
    return result


def parse_ctts(raw, sample_count):
    if raw is None:
        return [0] * sample_count
    payload = box_payload(raw)
    if len(payload) < 8:
        raise RuntimeError("Invalid ctts box")
    version, count, offset, result = payload[0], struct.unpack_from(">I", payload, 4)[0], 8, []
    for _ in range(count):
        if offset + 8 > len(payload):
            raise RuntimeError("Truncated ctts entry")
        samples = struct.unpack_from(">I", payload, offset)[0]
        value = struct.unpack_from(">i" if version == 1 else ">I", payload, offset + 4)[0]
        result.extend([value] * samples)
        offset += 8
    if len(result) != sample_count:
        raise RuntimeError("ctts/stts sample count mismatch")
    return result


def build_stts_box(sample_count):
    return make_box(b"stts", b"\0\0\0\0" + struct.pack(">III", 1, sample_count, STTS_DELTA))


def build_ctts_box(offsets):
    payload = bytearray(b"\1\0\0\0" + struct.pack(">I", len(offsets)))
    for value in offsets:
        payload += struct.pack(">Ii", 1, value)
    return make_box(b"ctts", bytes(payload))


def build_special_timing(stts, ctts):
    durations = parse_stts(stts)
    offsets = parse_ctts(ctts, len(durations))
    new_offsets = special_offsets(durations, offsets)
    return build_stts_box(len(durations)), build_ctts_box(new_offsets), len(durations)


def build_btrt_box():
    return make_box(b"btrt", struct.pack(">III", 0, VIDEO_BITRATE_K * 1000, 0))


def patch_sample_entry(raw):
    _, kind, header = box_header(raw)
    if kind not in {b"avc1", b"avc3"} or len(raw) < header + 78:
        return raw
    prefix, children = raw[:header + 78], raw[header + 78:]
    output, replaced = [], False
    for child_kind, child, _ in iter_boxes(children):
        if child_kind == b"btrt":
            output.append(build_btrt_box())
            replaced = True
        else:
            output.append(child)
    if not replaced:
        output.append(build_btrt_box())
    return make_box(kind, prefix[header:] + b"".join(output))


def patch_stsd(raw):
    payload = box_payload(raw)
    if len(payload) < 8:
        raise RuntimeError("Invalid stsd box")
    count = struct.unpack_from(">I", payload, 4)[0]
    entries = list(iter_boxes(payload[8:]))
    if len(entries) != count:
        raise RuntimeError("Invalid stsd entry count")
    return make_box(b"stsd", payload[:8] + b"".join(patch_sample_entry(entry) for _, entry, _ in entries))


def is_video_trak(raw):
    for kind, mdia, _ in iter_boxes(box_payload(raw)):
        if kind != b"mdia":
            continue
        for child_kind, child, _ in iter_boxes(box_payload(mdia)):
            if child_kind == b"hdlr":
                payload = box_payload(child)
                return len(payload) >= 12 and payload[8:12] == b"vide"
    return False


def patch_container(raw, target, patcher):
    _, kind, _ = box_header(raw)
    output, result = [], None
    for child_kind, child, _ in iter_boxes(box_payload(raw)):
        if child_kind == target:
            child, result = patcher(child)
        output.append(child)
    if result is None:
        raise RuntimeError(f"Missing MP4 box {target!r}")
    return make_box(kind, b"".join(output)), result


def patch_stbl(raw):
    children = list(iter_boxes(box_payload(raw)))
    stts = next((box for kind, box, _ in children if kind == b"stts"), None)
    ctts = next((box for kind, box, _ in children if kind == b"ctts"), None)
    if stts is None:
        raise RuntimeError("Missing stts box")
    new_stts, new_ctts, sample_count = build_special_timing(stts, ctts)
    output, inserted_ctts = [], False
    for kind, child, _ in children:
        if kind == b"stsd":
            child = patch_stsd(child)
        elif kind == b"stts":
            child = new_stts
        elif kind == b"ctts":
            child, inserted_ctts = new_ctts, True
        output.append(child)
    if not inserted_ctts:
        stts_index = next(index for index, child in enumerate(output) if box_header(child)[1] == b"stts")
        output.insert(stts_index + 1, new_ctts)
    return make_box(b"stbl", b"".join(output)), sample_count


def patch_video_trak(raw):
    def patch_mdia(mdia):
        def patch_minf(minf):
            return patch_container(minf, b"stbl", patch_stbl)
        return patch_container(mdia, b"minf", patch_minf)
    return patch_container(raw, b"mdia", patch_mdia)


def patch_moov(raw):
    output, sample_count = [], None
    for kind, child, _ in iter_boxes(box_payload(raw)):
        if kind == b"trak" and is_video_trak(child):
            child, sample_count = patch_video_trak(child)
        output.append(child)
    if sample_count is None:
        raise RuntimeError("Video track not found in moov")
    return make_box(b"moov", b"".join(output)), sample_count


def shift_chunk_box(raw, delta):
    _, kind, _ = box_header(raw)
    payload = box_payload(raw)
    if len(payload) < 8:
        raise RuntimeError("Invalid chunk offset box")
    count = struct.unpack_from(">I", payload, 4)[0]
    step, code = (4, ">I") if kind == b"stco" else (8, ">Q")
    if len(payload) < 8 + count * step:
        raise RuntimeError("Truncated chunk offset box")
    values = [struct.unpack_from(code, payload, 8 + index * step)[0] + delta for index in range(count)]
    if kind == b"stco" and any(value > 0xFFFFFFFF for value in values):
        kind, code = b"co64", ">Q"
    return make_box(kind, payload[:4] + struct.pack(">I", count) + b"".join(struct.pack(code, value) for value in values))


def shift_offsets(raw, delta):
    _, kind, _ = box_header(raw)
    if kind in {b"stco", b"co64"}:
        return shift_chunk_box(raw, delta)
    if kind not in {b"moov", b"trak", b"mdia", b"minf", b"stbl"}:
        return raw
    return make_box(kind, b"".join(shift_offsets(child, delta) for _, child, _ in iter_boxes(box_payload(raw))))


def scan_top_level(path):
    boxes, total = [], path.stat().st_size
    with path.open("rb") as stream:
        offset = 0
        while offset < total:
            stream.seek(offset)
            header_data = stream.read(16)
            if len(header_data) < 8:
                raise RuntimeError("Truncated top-level MP4 box")
            size32, kind = struct.unpack_from(">I4s", header_data)
            header = 16 if size32 == 1 else 8
            box_size = (struct.unpack_from(">Q", header_data, 8)[0] if size32 == 1 else
                        total - offset if size32 == 0 else size32)
            if box_size < header or offset + box_size > total:
                raise RuntimeError(f"Invalid top-level MP4 box {kind!r}")
            boxes.append((kind, offset, box_size, header))
            offset += box_size
    return boxes


def rewrite_mp4_timing(source, destination):
    boxes = scan_top_level(source)
    ftyp_info = next((box for box in boxes if box[0] == b"ftyp"), None)
    moov_info = next((box for box in boxes if box[0] == b"moov"), None)
    mdat_info = next((box for box in boxes if box[0] == b"mdat"), None)
    if not all((ftyp_info, moov_info, mdat_info)):
        raise RuntimeError("MP4 requires ftyp, moov and mdat boxes")
    with source.open("rb") as stream:
        def read_box(info):
            stream.seek(info[1])
            return stream.read(info[2])
        ftyp = read_box(ftyp_info)
        patched, sample_count = patch_moov(read_box(moov_info))

    others = [box for box in boxes if box not in (ftyp_info, moov_info)]
    old_mdat_data = mdat_info[1] + mdat_info[3]
    shifted = patched
    for _ in range(3):
        before_mdat = len(ftyp) + len(shifted) + sum(box[2] for box in others[:others.index(mdat_info)])
        delta = before_mdat + mdat_info[3] - old_mdat_data
        candidate = shift_offsets(patched, delta)
        if len(candidate) == len(shifted):
            shifted = candidate
            break
        shifted = candidate
    with source.open("rb") as reader, destination.open("wb") as writer:
        writer.write(ftyp)
        writer.write(shifted)
        for _, offset, size, _ in others:
            reader.seek(offset)
            remaining = size
            while remaining:
                chunk = reader.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("Unexpected end of MP4")
                writer.write(chunk)
                remaining -= len(chunk)
    return sample_count


def packet_count_is_plausible(actual, expected):
    return actual > 0 and abs(actual - expected) <= max(2, round(expected * 0.05))


def verify_output(ffprobe, output_path, expected_samples):
    duration, _ = probe_media(ffprobe, output_path)
    if duration <= 0:
        raise RuntimeError("Output duration is invalid")
    kinds = [box[0] for box in scan_top_level(output_path)]
    if kinds.index(b"moov") > kinds.index(b"mdat"):
        raise RuntimeError("Output moov box is not at the front")
    command = [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets",
               "-show_entries", "stream=nb_read_packets", "-of", "json", str(output_path)]
    info = run_json(command, f"FFprobe output verification {output_path}")
    streams = info.get("streams", [])
    packets = int(streams[0].get("nb_read_packets", 0)) if streams else 0
    if not packet_count_is_plausible(packets, expected_samples):
        raise RuntimeError(f"Output contains {packets} video packets; expected {expected_samples}")
    if packets != expected_samples:
        LOGGER.warning("Output packet count differs slightly: actual=%s expected=%s", packets,
                       expected_samples)


def run(input_path, output_path, ffmpeg, seed, encoder):
    run_many(input_path, [output_path], ffmpeg, seed, encoder)


def run_many(input_path, output_paths, ffmpeg, seed, encoder, on_output=None, should_stop=None,
             on_progress=None):
    input_path = Path(input_path)
    output_paths = [Path(path) for path in output_paths]
    if not output_paths:
        return 0
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe"))
    duration, has_audio, total_frames = probe_media(ffprobe, input_path, True)
    active_encoder = select_encoder(ffmpeg, encoder)
    for output_path in output_paths:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".abcache_", dir=output_paths[0].parent) as directory:
        directory = Path(directory)
        def cache_progress(current, total):
            if on_progress:
                on_progress("缓存视频帧", current, total, -1)

        try_cuda = active_encoder == "h264_nvenc"
        try:
            cache = decode_to_cache(ffmpeg, input_path, directory / "random_frames.bin", try_cuda,
                                    total_frames, cache_progress)
        except RuntimeError:
            if not try_cuda:
                raise
            LOGGER.warning("CUDA decoding unavailable; retrying with CPU decoding")
            cache = decode_to_cache(ffmpeg, input_path, directory / "random_frames.bin", False,
                                    total_frames, cache_progress)
        completed = 0
        for index, output_path in enumerate(output_paths):
            if should_stop and should_stop():
                break
            order = shuffled_order(len(cache.items), None if seed is None else seed + index)
            temp_path = directory / f"interleaved60_{index}.mp4"
            ready_path = directory / f".{output_path.name}.ready.mp4"
            encode_progress = (lambda current, total, i=index: on_progress(
                f"生成第 {i + 1} 份", current, total, i)) if on_progress else None
            try:
                encode_interleaved(ffmpeg, input_path, temp_path, duration, has_audio, cache, order,
                                   active_encoder, encode_progress)
            except RuntimeError:
                if active_encoder != "h264_nvenc":
                    raise
                LOGGER.exception("NVENC failed during processing; retrying this output with CPU libx264")
                temp_path.unlink(missing_ok=True)
                active_encoder = "libx264"
                encode_interleaved(ffmpeg, input_path, temp_path, duration, has_audio, cache, order,
                                   active_encoder, encode_progress)
            sample_count = rewrite_mp4_timing(temp_path, ready_path)
            verify_output(ffprobe, ready_path, sample_count)
            os.replace(ready_path, output_path)
            temp_path.unlink(missing_ok=True)
            completed += 1
            if on_output:
                on_output(index, output_path)
        return completed


def self_test():
    source_stts = make_box(b"stts", b"\0\0\0\0" + struct.pack(">III", 1, 4, 256))
    stts, ctts, count = build_special_timing(source_stts, None)
    assert count == 4 and parse_stts(stts) == [512] * 4
    assert parse_ctts(ctts, 4) == [0, -256, -512, -768]
    order = shuffled_order(20, 1)
    assert set(order) == set(range(20)) and order != list(range(20))
    assert packet_count_is_plausible(12979, 13457)
    assert not packet_count_is_plausible(10000, 13457)
    with tempfile.TemporaryDirectory() as directory:
        frames = [bytes([index]) * 1024 for index in range(8)]
        cache = FrameCache(Path(directory) / "frames.bin")
        cache_frames(cache, frames, workers=3)
        cache.seal()
        assert list(cache.iter_order(reversed(range(8)), workers=3)) == frames[::-1]
    print("self-test passed")


def main():
    parser = argparse.ArgumentParser(description="Interleave a video with a shuffled copy of all its frames")
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--encoder", choices=("h264_nvenc", "libx264"), default="h264_nvenc")
    local_ffmpeg = Path(__file__).resolve().parent / "ffmpeg" / "ffmpeg.exe"
    legacy_ffmpeg = Path(__file__).resolve().parent.parent / "ffmpeg" / "ffmpeg.exe"
    parser.add_argument("--ffmpeg", default=str(local_ffmpeg if local_ffmpeg.is_file() else legacy_ffmpeg))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.input or not args.output:
        parser.error("input and output are required")
    run(args.input, args.output, args.ffmpeg, args.seed, args.encoder)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, BrokenPipeError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
