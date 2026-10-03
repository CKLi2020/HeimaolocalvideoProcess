#!/usr/bin/env python3
"""Reproduce the captured shipinghao_chuanshanjia_v15 FFmpeg workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import secrets
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from engine.native_core import core as _native_core


MODE_WIDTH = 576
MODE_HEIGHT = 1248
MODE_FPS = 60
THREADS = 12
RANDOM_BRANCH_FPS = 5
CAPTURED_RANDOM_SEED = 84106055771035
DECLARED_VIDEO_FPS = 30
# The captured FFmpeg build used 1000; newer builds default to an automatic movie timescale.
MOVIE_TIMESCALE = 1000
MP4_CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"udta"}
X264_PARAMS = (
    "bframes=3:b-adapt=1:b-pyramid=2:keyint=18:keyint-min=10:"
    "scenecut=0:ref=3:me=hex:subme=4:trellis=0:8x8dct=0:weightp=1:"
    "rc-lookahead=20:rc=cbr:vbv-maxrate=9000:vbv-bufsize=18000:nal-hrd=vbr"
)
STREAM_FIELDS = (
    "codec_type",
    "codec_name",
    "profile",
    "level",
    "codec_tag_string",
    "width",
    "height",
    "sample_fmt",
    "sample_rate",
    "channels",
    "channel_layout",
    "sample_aspect_ratio",
    "display_aspect_ratio",
    "pix_fmt",
    "field_order",
    "color_range",
    "color_space",
    "color_transfer",
    "color_primaries",
    "r_frame_rate",
    "avg_frame_rate",
    "time_base",
    "start_time",
    "duration",
    "nb_frames",
)
STABLE_STREAM_TAGS = ("language", "handler_name", "vendor_id")
STABLE_FORMAT_TAGS = ("major_brand", "minor_version", "compatible_brands")
FORMAT_FIELDS = ("format_name", "start_time", "duration")


def resolve_tool(name: str, script_dir: Path) -> str:
    candidates = (
        script_dir / "bin" / f"{name}.exe",
        script_dir / "ffmpeg" / f"{name}.exe",
        script_dir / f"{name}.exe",
        script_dir / "bin" / name,
        script_dir / name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    from_path = shutil.which(name) or shutil.which(f"{name}.exe")
    if from_path:
        return from_path
    raise FileNotFoundError(f"Could not find {name} beside the worker, in bin/, or on PATH")


def run_probe(ffprobe: str, path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-show_programs",
            "-show_chapters",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc


def stable_mapping(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def signature(probe: dict[str, Any]) -> dict[str, Any]:
    streams = []
    for stream in probe.get("streams", []):
        entry = stable_mapping(stream, STREAM_FIELDS)
        entry["disposition"] = stream.get("disposition", {})
        entry["tags"] = stable_mapping(stream.get("tags", {}), STABLE_STREAM_TAGS)
        streams.append(entry)
    fmt = probe.get("format", {})
    return {
        "streams": streams,
        "format": stable_mapping(fmt, FORMAT_FIELDS),
        "format_tags": stable_mapping(fmt.get("tags", {}), STABLE_FORMAT_TAGS),
        "programs": probe.get("programs", []),
        "chapters": probe.get("chapters", []),
    }


def compare_values(expected: Any, actual: Any, path: str, differences: list[dict[str, Any]]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected):
            if key not in actual:
                differences.append({"field": f"{path}.{key}", "expected": expected[key], "actual": None})
            else:
                compare_values(expected[key], actual[key], f"{path}.{key}", differences)
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            differences.append(
                {"field": f"{path}.length", "expected": len(expected), "actual": len(actual)}
            )
            return
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            compare_values(expected_item, actual_item, f"{path}[{index}]", differences)
        return
    if expected != actual:
        differences.append({"field": path, "expected": expected, "actual": actual})


def compare_signatures(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    compare_values(expected, actual, "signature", differences)
    stream_counts_match = len(expected["streams"]) == len(actual["streams"])
    frame_counts_match = stream_counts_match and all(
        expected_stream.get("nb_frames") == actual_stream.get("nb_frames")
        for expected_stream, actual_stream in zip(expected["streams"], actual["streams"])
    )
    durations_match = stream_counts_match and all(
        expected_stream.get("duration") == actual_stream.get("duration")
        for expected_stream, actual_stream in zip(expected["streams"], actual["streams"])
    )
    if frame_counts_match and durations_match:
        expected_duration = expected["format"].get("duration")
        actual_duration = actual["format"].get("duration")
        if expected_duration is not None and actual_duration is not None:
            try:
                if abs(float(expected_duration) - float(actual_duration)) <= 0.001:
                    differences = [
                        difference
                        for difference in differences
                        if difference["field"] != "signature.format.duration"
                    ]
            except ValueError:
                pass
    return differences


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_command(
    ffmpeg: str,
    source: Path,
    output: Path,
    threads: int,
    video_encoder: str = "libx264",
    encoder_options: Sequence[str] = (),
    random_enhance: bool = False,
    random_seed: int | None = None,
) -> list[str]:
    """Build the channel's FFmpeg command without starting a subprocess."""
    seed = random_seed if random_seed is not None else secrets.randbits(48)
    filters = _native_core.liuying_video_filter(seed, random_enhance)

    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-threads",
        str(threads),
        "-filter_threads",
        str(threads),
        "-filter_complex_threads",
        str(threads),
        "-i",
        str(source),
        "-vf",
        filters,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-fps_mode",
        "passthrough",
        "-c:v",
        video_encoder,
        "-profile:v",
        "main",
        "-level:v",
        "3.2",
        "-g",
        "18",
        "-b:v",
        "9000k",
        "-pix_fmt",
        "yuv420p",
    ]
    if video_encoder == "libx264":
        command.extend(
            [
                "-threads:v",
                str(threads),
                "-preset",
                "medium",
                "-x264-params",
                X264_PARAMS,
            ]
        )
    else:
        command.extend(encoder_options)
    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-video_track_timescale",
            "15360",
            "-movie_timescale",
            str(MOVIE_TIMESCALE),
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return command


def run_random_perspective_branch(
    ffmpeg: str,
    source: Path,
    seed: int,
    frame_count: int,
    raw_output: Path | None = None,
) -> None:
    """Reproduce the captured 5-fps perspective branch and optionally retain its raw frames."""
    source_args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-threads",
        str(THREADS),
        "-filter_threads",
        str(THREADS),
        "-hwaccel",
        "cuda",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        _native_core.liuying_base_filter() + ",fps=5",
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        str(THREADS),
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    perspective_args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-threads",
        "1",
        "-filter_threads",
        str(THREADS),
        "-f",
        "rawvideo",
        "-pixel_format",
        "yuv420p",
        "-video_size",
        f"{MODE_WIDTH}x{MODE_HEIGHT}",
        "-framerate",
        str(RANDOM_BRANCH_FPS),
        "-i",
        "pipe:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        _native_core.liuying_perspective_filter(seed),
        "-frames:v",
        str(frame_count),
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "1",
        "-f",
        "rawvideo",
        str(raw_output) if raw_output else "NUL",
    ]
    with tempfile.TemporaryFile() as source_errors, tempfile.TemporaryFile() as perspective_errors:
        decoder = subprocess.Popen(
            source_args,
            stdout=subprocess.PIPE,
            stderr=source_errors,
        )
        assert decoder.stdout is not None
        try:
            transformer = subprocess.Popen(
                perspective_args,
                stdin=decoder.stdout,
                stdout=subprocess.DEVNULL,
                stderr=perspective_errors,
            )
        except Exception:
            decoder.stdout.close()
            decoder.kill()
            decoder.wait()
            raise
        decoder.stdout.close()
        transform_code = transformer.wait()
        decoder_code = decoder.wait()
        source_errors.seek(0)
        source_message = source_errors.read().decode("utf-8", "replace").strip()
        perspective_errors.seek(0)
        perspective_message = perspective_errors.read().decode("utf-8", "replace").strip()
    if decoder_code or transform_code:
        raise RuntimeError(
            "Random perspective branch failed: "
            f"decode exit={decoder_code} ({source_message}); "
            f"perspective exit={transform_code} ({perspective_message})"
        )


def iter_mp4_boxes(data: bytes | bytearray, start: int, end: int):
    position = start
    while position < end:
        if end - position < 8:
            raise ValueError(f"Truncated MP4 box header at byte {position}")
        size, kind = struct.unpack_from(">I4s", data, position)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, position + 8)[0]
            header = 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            raise ValueError(f"Invalid MP4 box {kind!r} at byte {position}")
        yield kind, position, header, size
        position += size


def make_mp4_box(kind: bytes, payload: bytes | bytearray) -> bytes:
    if len(payload) + 8 > 0xFFFFFFFF:
        raise ValueError(f"MP4 box {kind!r} is too large for a 32-bit size")
    return struct.pack(">I4s", len(payload) + 8, kind) + bytes(payload)


def find_mp4_child(data: bytes | bytearray, start: int, end: int, kind: bytes) -> tuple[int, int] | None:
    for child_kind, position, header, size in iter_mp4_boxes(data, start, end):
        if child_kind == kind:
            return position + header, position + size
    return None


def track_handler_and_timescale(data: bytes | bytearray, start: int, end: int) -> tuple[bytes, int]:
    mdia = find_mp4_child(data, start, end, b"mdia")
    if mdia is None:
        return b"", 0
    hdlr = find_mp4_child(data, *mdia, b"hdlr")
    mdhd = find_mp4_child(data, *mdia, b"mdhd")
    handler = bytes(data[hdlr[0] + 8 : hdlr[0] + 12]) if hdlr else b""
    timescale = 0
    if mdhd:
        offset = 12 if data[mdhd[0]] == 0 else 20
        timescale = struct.unpack_from(">I", data, mdhd[0] + offset)[0]
    return handler, timescale


def presentation_times(stts: bytes | bytearray, ctts: bytes | bytearray | None) -> list[int]:
    decode_times: list[int] = []
    current = 0
    for index in range(struct.unpack_from(">I", stts, 4)[0]):
        count, delta = struct.unpack_from(">II", stts, 8 + index * 8)
        for _ in range(count):
            decode_times.append(current)
            current += delta
    offsets: list[int] = []
    if ctts is not None:
        entry_format = ">Ii" if ctts[0] == 1 else ">II"
        for index in range(struct.unpack_from(">I", ctts, 4)[0]):
            count, offset = struct.unpack_from(entry_format, ctts, 8 + index * 8)
            offsets.extend([offset] * count)
    else:
        offsets = [0] * len(decode_times)
    if len(offsets) != len(decode_times):
        raise ValueError("MP4 stts/ctts sample counts differ")
    return [decode + offset for decode, offset in zip(decode_times, offsets)]


def retime_stbl(
    data: bytes | bytearray, start: int, end: int, timescale: int, declared_fps: int
) -> tuple[bytes, dict[str, Any]]:
    children = list(iter_mp4_boxes(data, start, end))
    bodies = {kind: data[position + header : position + size] for kind, position, header, size in children}
    if b"stts" not in bodies:
        raise ValueError("Video track has no stts box")
    if timescale <= 0 or timescale % declared_fps:
        raise ValueError(f"Video timescale {timescale} is not divisible by {declared_fps}")
    pts = presentation_times(bodies[b"stts"], bodies.get(b"ctts"))
    delta = timescale // declared_fps
    offsets = [time - delta * index for index, time in enumerate(pts)]
    if any(offset < -(2**31) or offset >= 2**31 for offset in offsets):
        raise ValueError("Retimed composition offsets do not fit in ctts v1")
    new_stts = make_mp4_box(b"stts", struct.pack(">IIII", 0, 1, len(pts), delta))
    new_ctts = make_mp4_box(
        b"ctts",
        struct.pack(">II", 1 << 24, len(pts)) + b"".join(struct.pack(">Ii", 1, offset) for offset in offsets),
    )
    rebuilt = bytearray()
    inserted_ctts = b"ctts" in bodies
    for kind, position, _, size in children:
        if kind == b"stts":
            rebuilt += new_stts
            if not inserted_ctts and b"stss" not in bodies:
                rebuilt += new_ctts
                inserted_ctts = True
        elif kind == b"ctts":
            rebuilt += new_ctts
        elif kind == b"stss" and not inserted_ctts:
            rebuilt += data[position : position + size]
            rebuilt += new_ctts
            inserted_ctts = True
        else:
            rebuilt += data[position : position + size]
    return bytes(rebuilt), {"samples": len(pts), "stts_delta": delta, "pts": pts}


def shift_chunk_offsets(kind: bytes, body: bytes | bytearray, shift: int) -> bytes:
    count = struct.unpack_from(">I", body, 4)[0]
    entry_format = ">Q" if kind == b"co64" else ">I"
    width = 8 if kind == b"co64" else 4
    limit = 2**64 if kind == b"co64" else 2**32
    shifted = bytearray(body[:8])
    for index in range(count):
        value = struct.unpack_from(entry_format, body, 8 + index * width)[0] + shift
        if not 0 <= value < limit:
            raise ValueError(f"Shifted {kind.decode()} chunk offset is out of range")
        shifted += struct.pack(entry_format, value)
    return bytes(shifted)


def rebuild_mp4_container(
    data: bytes | bytearray,
    start: int,
    end: int,
    declared_fps: int,
    shift: int,
    track: tuple[bytes, int] = (b"", 0),
    results: list[dict[str, Any]] | None = None,
) -> bytes:
    rebuilt = bytearray()
    for kind, position, header, size in iter_mp4_boxes(data, start, end):
        body_start, body_end = position + header, position + size
        if kind == b"trak":
            child_track = track_handler_and_timescale(data, body_start, body_end)
            rebuilt += make_mp4_box(
                kind,
                rebuild_mp4_container(data, body_start, body_end, declared_fps, shift, child_track, results),
            )
        elif kind == b"stbl" and track[0] == b"vide":
            retimed, info = retime_stbl(data, body_start, body_end, track[1], declared_fps)
            if results is not None:
                results.append(info)
            rebuilt += make_mp4_box(
                kind, rebuild_mp4_container(retimed, 0, len(retimed), declared_fps, shift, (b"", 0), results)
            )
        elif kind in (b"moov", b"mdia", b"minf", b"stbl"):
            rebuilt += make_mp4_box(
                kind, rebuild_mp4_container(data, body_start, body_end, declared_fps, shift, track, results)
            )
        elif kind in (b"stco", b"co64") and shift:
            rebuilt += make_mp4_box(kind, shift_chunk_offsets(kind, data[body_start:body_end], shift))
        else:
            rebuilt += data[position : position + size]
    return bytes(rebuilt)


def retime_video_track(path: Path, declared_fps: int) -> dict[str, Any]:
    """Match the tool's post-encode MP4 rewrite: constant declared-rate stts plus signed ctts."""
    data = path.read_bytes()
    top_level = list(iter_mp4_boxes(data, 0, len(data)))
    moov = next((box for box in top_level if box[0] == b"moov"), None)
    if moov is None:
        raise ValueError("Output has no moov box")
    _, moov_position, moov_header, moov_size = moov
    moov_before_media = all(moov_position < position for kind, position, _, _ in top_level if kind == b"mdat")
    body = (moov_position + moov_header, moov_position + moov_size)
    trial = make_mp4_box(b"moov", rebuild_mp4_container(data, *body, declared_fps, 0))
    shift = len(trial) - moov_size if moov_before_media else 0
    results: list[dict[str, Any]] = []
    new_moov = make_mp4_box(b"moov", rebuild_mp4_container(data, *body, declared_fps, shift, results=results))
    if len(results) != 1:
        raise ValueError(f"Expected exactly one video track to retime, found {len(results)}")
    if len(new_moov) - moov_size != shift and moov_before_media:
        raise ValueError("MP4 moov size changed between retiming passes")
    rewritten = data[:moov_position] + new_moov + data[moov_position + moov_size :]
    check_moov = find_mp4_child(rewritten, 0, len(rewritten), b"moov")
    verified_pts: list[int] = []
    for kind, position, header, size in iter_mp4_boxes(rewritten, *check_moov):
        if kind != b"trak":
            continue
        handler, _ = track_handler_and_timescale(rewritten, position + header, position + size)
        if handler != b"vide":
            continue
        mdia = find_mp4_child(rewritten, position + header, position + size, b"mdia")
        minf = find_mp4_child(rewritten, *mdia, b"minf")
        stbl = find_mp4_child(rewritten, *minf, b"stbl")
        stts = find_mp4_child(rewritten, *stbl, b"stts")
        ctts = find_mp4_child(rewritten, *stbl, b"ctts")
        verified_pts = presentation_times(rewritten[stts[0] : stts[1]], rewritten[ctts[0] : ctts[1]])
    if verified_pts != results[0]["pts"]:
        raise ValueError("Retimed presentation timestamps differ from the encoded output")
    temporary = path.with_name(path.name + ".retime.tmp")
    temporary.write_bytes(rewritten)
    temporary.replace(path)
    return {
        "declared_fps": declared_fps,
        "samples": results[0]["samples"],
        "stts_delta": results[0]["stts_delta"],
        "ctts_version": 1,
        "moov_size_delta": len(new_moov) - moov_size,
        "chunk_offset_shift": shift,
        "presentation_timestamps_preserved": True,
    }


def encode(
    ffmpeg: str,
    source: Path,
    output: Path,
    random_seed: int = CAPTURED_RANDOM_SEED,
) -> None:
    preprocess_args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-threads",
        str(THREADS),
        "-filter_threads",
        str(THREADS),
        "-hwaccel",
        "cuda",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        _native_core.liuying_base_filter(),
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        str(THREADS),
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    encode_args = [
        ffmpeg,
        "-nostdin",
        "-nostats",
        "-stats_period",
        "0.25",
        "-progress",
        "pipe:1",
        "-filter_complex_threads",
        str(THREADS),
        "-filter_threads",
        str(THREADS),
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "yuv420p",
        "-s",
        f"{MODE_WIDTH}x{MODE_HEIGHT}",
        "-r",
        str(MODE_FPS),
        "-i",
        "pipe:0",
        "-threads",
        str(THREADS),
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-level",
        "3.2",
        "-bf",
        "3",
        "-refs",
        "3",
        "-g",
        "18",
        "-preset",
        "medium",
        "-threads:v",
        str(THREADS),
        "-x264-params",
        X264_PARAMS,
        "-b:v",
        "9000k",
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        "15360",
        "-vf",
        "setsar=1," + _native_core.liuying_flash_filter(random_seed),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movie_timescale",
        str(MOVIE_TIMESCALE),
        "-movflags",
        "+faststart",
        str(output),
    ]

    with tempfile.TemporaryFile() as preprocess_errors, tempfile.TemporaryFile() as encode_errors:
        preprocess = subprocess.Popen(
            preprocess_args,
            stdout=subprocess.PIPE,
            stderr=preprocess_errors,
        )
        assert preprocess.stdout is not None
        try:
            encoder = subprocess.Popen(
                encode_args,
                stdin=preprocess.stdout,
                stdout=subprocess.DEVNULL,
                stderr=encode_errors,
            )
        except Exception:
            preprocess.stdout.close()
            preprocess.kill()
            preprocess.wait()
            raise
        preprocess.stdout.close()
        encode_code = encoder.wait()
        preprocess_code = preprocess.wait()
        if preprocess_errors.tell():
            preprocess_errors.seek(0)
            preprocess_message = preprocess_errors.read().decode("utf-8", "replace").strip()
        else:
            preprocess_message = ""
        if encode_errors.tell():
            encode_errors.seek(0)
            encode_message = encode_errors.read().decode("utf-8", "replace").strip()
        else:
            encode_message = ""
    if preprocess_code or encode_code:
        raise RuntimeError(
            "FFmpeg pipeline failed: "
            f"preprocess exit={preprocess_code} ({preprocess_message}); "
            f"encode exit={encode_code} ({encode_message})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--random-seed",
        type=int,
        default=CAPTURED_RANDOM_SEED,
        help="Base seed for the captured FFmpeg perspective branch",
    )
    parser.add_argument("--ffmpeg", type=Path, help="Override FFmpeg executable")
    parser.add_argument("--ffprobe", type=Path, help="Override ffprobe executable")
    parser.add_argument(
        "--random-branch-output",
        type=Path,
        help="Preserve reproduced random-branch frames as raw 576x1248 yuv420p",
    )
    parser.add_argument(
        "--declared-fps",
        type=int,
        default=DECLARED_VIDEO_FPS,
        help="Declared video rate written into the MP4 stts table (captured tool value: 30)",
    )
    args = parser.parse_args()

    report_path = args.report or args.output.with_suffix(".verification.json")
    report: dict[str, Any] = {
        "mode": "shipinghao_chuanshanjia_v15",
        "input": str(args.input.resolve()),
        "output": str(args.output.resolve()),
        "reference": str(args.reference.resolve()),
        "policy": {
            "compared": [
                "stream order/count/types, codec/profile/level/tag, dimensions, pixel/audio properties, "
                "frame rates, time bases, durations/counts, dispositions, stable tags, container, programs, chapters; "
                "optional fields are compared when present in the reference probe"
            ],
            "excluded": [
                "file size, bitrate, encoded bytes, whole-file hashes, volatile metadata and creation timestamps"
            ],
            "duration_tolerance": "format duration <= 1 ms only if per-stream durations and frame counts match",
            "encoder": "libx264; active reference is the captured 1_4 output produced by the x264 invocation",
        },
        "mp4_timing_observation": (
            "The tool's final MP4 keeps 60 fps presentation timestamps but rewrites the video stts to one "
            "constant delta of timescale/30 and stores per-sample signed ctts v1 offsets, so ffprobe reports "
            "30/1. The worker applies the same table rewrite after encoding without touching mdat."
        ),
        "random_perspective": {
            "base_seed": args.random_seed,
            "seed_per_input_frame": "protected native-core schedule",
            "input_fps": RANDOM_BRANCH_FPS,
            "frame_limit": None,
            "branch_consumer": "unknown; secure core's raw-pipe synchronization/composition was not captured",
            "integration_reconstruction": (
                "The local channel applies the seeded perspective transform to output frames 10, 20, "
                "30, 40, and 50 in each 60-frame second, matching the captured 5-fps visual cadence."
            ),
            "reconstruction": (
                "Frames are regenerated from the source using the captured main-video filter followed by "
                "fps=5. The running process's actual raw pipe bytes were not captured."
            ),
            "alignment_method": (
                "Candidate 5-fps correspondence is based on output timestamps; this does not prove the "
                "secure core used identical frame selection or composition."
            ),
        },
        "randomness_observation": {
            "captured_filter_graph": (
                "fps=60,scale=576:1248:force_original_aspect_ratio=decrease,"
                "pad=576:1248:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
            ),
            "captured_encoder": (
                "The main-video libx264 command used 12 threads and CBR/rc-lookahead=20. A separate "
                "captured FFmpeg command applies the seeded perspective random branch."
            ),
            "same_input_sha256": (
                "da9c13469b788ccb1b02e1c1ec7af82017f12790e522b45cafe3c49fea22378f"
            ),
            "evidence": {
                "repeated_preprocess_frames": 2802,
                "identical_repeated_preprocess_frames": 2802,
                "tool_output_comparison_frames": 2802,
                "identical_tool_output_frames": 0,
                "tool_output_frames_with_ssim_below_0_9": 220,
                "tool_output_mean_per_frame_ssim": 0.965213834,
                "tool_output_median_per_frame_ssim": 0.998034,
                "repeated_12_thread_x264_test_frames": 2802,
                "identical_repeated_12_thread_x264_frames": 155,
                "repeated_12_thread_x264_mean_per_frame_ssim": 0.999366901,
                "repeated_1_thread_x264_test_frames": 2802,
                "identical_repeated_1_thread_x264_frames": 2802,
            },
            "assessment": (
                "The FFmpeg preprocessing was repeatable, but 220/2802 paired tool-output frames had "
                "SSIM below 0.9 and sample frames visibly changed scene composition/text. The captured "
                "main-video preprocessing is repeatable, while a separate randomized perspective branch "
                "was captured. A fresh tool run changed exactly 264 of 3168 output frames at the 5-fps "
                "schedule reproduced by the local channel. The secure core's exact pipe synchronization remains "
                "unobserved, so this is a validated visual-schedule reconstruction, not a claim of identical "
                "internal composition. Separate controlled x264 tests also showed small thread-dependent pixel "
                "variation (mean SSIM about 0.99937 for a 12-thread repeat and exact repeatability at one "
                "thread); that does not explain the larger scene changes."
            ),
        },
    }

    try:
        input_path = args.input.resolve(strict=True)
        reference_path = args.reference.resolve(strict=True)
        output_path = args.output.resolve()
        if input_path == output_path or reference_path == output_path:
            raise ValueError("Input, output, and reference paths must be different.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = (
            str(args.ffmpeg.resolve(strict=True))
            if args.ffmpeg
            else resolve_tool("ffmpeg", Path(__file__).resolve().parent)
        )
        ffprobe = (
            str(args.ffprobe.resolve(strict=True))
            if args.ffprobe
            else resolve_tool("ffprobe", Path(__file__).resolve().parent)
        )
        report["tools"] = {"ffmpeg": ffmpeg, "ffprobe": ffprobe}
        report["sample_sha256"] = {
            "input": sha256(input_path),
            "reference": sha256(reference_path),
        }
        input_probe = run_probe(ffprobe, input_path)
        input_video = next(
            (stream for stream in input_probe.get("streams", []) if stream.get("codec_type") == "video"),
            None,
        )
        if input_video is None:
            raise ValueError("Input has no video stream.")
        duration = float(input_video.get("duration") or input_probe.get("format", {}).get("duration"))
        random_frame_count = round(duration * RANDOM_BRANCH_FPS)
        report["random_perspective"]["frame_limit"] = random_frame_count
        report["random_perspective"]["filter"] = _native_core.liuying_perspective_filter(args.random_seed)
        random_branch_output = (
            args.random_branch_output.resolve()
            if args.random_branch_output
            else None
        )
        if random_branch_output:
            if random_branch_output in (input_path, reference_path, output_path):
                raise ValueError("Random-branch output must be a separate file.")
            random_branch_output.parent.mkdir(parents=True, exist_ok=True)
            report["random_perspective"]["raw_output"] = str(random_branch_output)
            report["random_perspective"]["frame_size_bytes"] = (
                MODE_WIDTH * MODE_HEIGHT * 3 // 2
            )
        run_random_perspective_branch(
            ffmpeg,
            input_path,
            args.random_seed,
            random_frame_count,
            random_branch_output,
        )
        if random_branch_output:
            expected_size = random_frame_count * MODE_WIDTH * MODE_HEIGHT * 3 // 2
            actual_size = random_branch_output.stat().st_size
            if actual_size != expected_size:
                raise RuntimeError(
                    f"Random-branch raw size mismatch: expected {expected_size}, got {actual_size}"
                )
            report["random_perspective"]["raw_output_size"] = actual_size
            report["random_perspective"]["raw_output_sha256"] = sha256(random_branch_output)
        report["random_perspective"]["executed"] = True
        encode(ffmpeg, input_path, output_path, args.random_seed)
        report["mp4_timing_rewrite"] = retime_video_track(output_path, args.declared_fps)
        expected_probe = run_probe(ffprobe, reference_path)
        actual_probe = run_probe(ffprobe, output_path)
        expected_signature = signature(expected_probe)
        actual_signature = signature(actual_probe)
        differences = compare_signatures(expected_signature, actual_signature)
        report.update(
            {
                "expected_signature": expected_signature,
                "actual_signature": actual_signature,
                "differences": differences,
                "passed": not differences,
                "result": "pass" if not differences else "feature_mismatch",
            }
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"result": report["result"], "report": str(report_path), "differences": differences}, ensure_ascii=False))
        return 0 if not differences else 2
    except Exception as exc:
        report.update({"passed": False, "result": "processing_failure", "error": str(exc)})
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Processing failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
