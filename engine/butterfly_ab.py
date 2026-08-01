"""2026-08-01 00:50 恢复版：媒体内 A头+B+A尾，MP4 编辑列表播放时跳过 B。"""

import argparse
import json
import random
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def run(cmd, stop_event=None):
    process = subprocess.Popen([str(x) for x in cmd])
    while process.poll() is None:
        if stop_event and stop_event.wait(0.2):
            process.terminate()
            process.wait()
            raise InterruptedError("用户已停止处理")
        if not stop_event:
            process.wait()
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, cmd)


def probe(path):
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_streams", "-show_format",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def video_info(path):
    info = probe(path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    return (
        float(info["format"]["duration"]),
        any(s["codec_type"] == "audio" for s in info["streams"]),
    )


def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            break
        yield pos, size, kind, header
        pos += size


def box(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def children(data, parent):
    pos, size, _, header = parent
    return list(boxes(data, pos + header, pos + size))


def patch_duration(raw, kind, seconds, timescale=None):
    out = bytearray(raw)
    version = out[8]
    if kind == b"mvhd":
        scale_at = 28 if version else 20
        duration_at = 32 if version else 24
        scale = struct.unpack_from(">I", out, scale_at)[0]
    else:
        duration_at = 36 if version else 28
        scale = timescale
    fmt = ">Q" if version else ">I"
    struct.pack_into(fmt, out, duration_at, round(seconds * scale))
    return bytes(out), scale


def track_timescale(data, trak):
    mdia = next(x for x in children(data, trak) if x[2] == b"mdia")
    mdhd = next(x for x in children(data, mdia) if x[2] == b"mdhd")
    pos = mdhd[0]
    return struct.unpack_from(">I", data, pos + (28 if data[pos + 8] else 20))[0]


def edit_list(movie_scale, media_scale, head, hidden, tail):
    entries = (
        struct.pack(">Qqhh", round(head * movie_scale), 0, 1, 0)
        + struct.pack(
            ">Qqhh",
            round(tail * movie_scale),
            round((head + hidden) * media_scale),
            1, 0,
        )
    )
    return box(b"edts", box(b"elst", b"\x01\x00\x00\x00" + struct.pack(">I", 2) + entries))


CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"dinf", b"edts"}


def shift_chunk_offsets(raw, delta):
    """moov 在 mdat 前且 moov 变大时，同步修正 stco/co64。"""
    rebuilt = []
    for pos, size, kind, header in boxes(raw):
        payload = raw[pos + header:pos + size]
        if kind in CONTAINERS:
            payload = shift_chunk_offsets(payload, delta)
        elif kind in (b"stco", b"co64"):
            out = bytearray(payload)
            count = struct.unpack_from(">I", out, 4)[0]
            fmt, width = (">I", 4) if kind == b"stco" else (">Q", 8)
            for i in range(count):
                at = 8 + i * width
                struct.pack_into(fmt, out, at, struct.unpack_from(fmt, out, at)[0] + delta)
            payload = bytes(out)
        rebuilt.append(box(kind, payload))
    return b"".join(rebuilt)


def hide_middle(path, visible_duration, head, hidden):
    data = path.read_bytes()
    top = list(boxes(data))
    moov = next(x for x in top if x[2] == b"moov")
    mdat = next(x for x in top if x[2] == b"mdat")
    mvhd = next(x for x in children(data, moov) if x[2] == b"mvhd")
    raw_mvhd = data[mvhd[0]:mvhd[0] + mvhd[1]]
    new_mvhd, movie_scale = patch_duration(raw_mvhd, b"mvhd", visible_duration)
    tail = visible_duration - head

    rebuilt = []
    for child in children(data, moov):
        pos, size, kind, header = child
        if kind == b"mvhd":
            rebuilt.append(new_mvhd)
            continue
        if kind != b"trak":
            rebuilt.append(data[pos:pos + size])
            continue

        media_scale = track_timescale(data, child)
        parts = []
        inserted = False
        for item in children(data, child):
            p, n, k, _ = item
            if k == b"tkhd":
                patched, _ = patch_duration(data[p:p + n], b"tkhd", visible_duration, movie_scale)
                parts.append(patched)
            elif k == b"edts":
                parts.append(edit_list(movie_scale, media_scale, head, hidden, tail))
                inserted = True
            else:
                parts.append(data[p:p + n])
                if k == b"mdia" and not inserted:
                    parts.insert(-1, edit_list(movie_scale, media_scale, head, hidden, tail))
                    inserted = True
        rebuilt.append(box(b"trak", b"".join(parts)))

    new_moov = box(b"moov", b"".join(rebuilt))
    if moov[0] < mdat[0]:
        delta = len(new_moov) - moov[1]
        new_moov = shift_chunk_offsets(new_moov, delta)
    path.write_bytes(data[:moov[0]] + new_moov + data[moov[0] + moov[1]:])


def validate_edit_lists(path, visible_duration, head, hidden):
    data = path.read_bytes()
    moov = next(x for x in boxes(data) if x[2] == b"moov")
    mvhd = next(x for x in children(data, moov) if x[2] == b"mvhd")
    mvhd_pos = mvhd[0]
    movie_scale = struct.unpack_from(
        ">I", data, mvhd_pos + (28 if data[mvhd_pos + 8] else 20)
    )[0]
    tracks = [x for x in children(data, moov) if x[2] == b"trak"]
    if not tracks:
        raise RuntimeError("编辑列表校验失败：没有音视频轨")

    for track in tracks:
        media_scale = track_timescale(data, track)
        edts = next((x for x in children(data, track) if x[2] == b"edts"), None)
        if not edts:
            raise RuntimeError("编辑列表校验失败：轨道缺少 edts")
        elst = next((x for x in children(data, edts) if x[2] == b"elst"), None)
        if not elst:
            raise RuntimeError("编辑列表校验失败：轨道缺少 elst")
        pos = elst[0]
        version = data[pos + 8]
        count = struct.unpack_from(">I", data, pos + 12)[0]
        if version != 1 or count != 2:
            raise RuntimeError(f"编辑列表校验失败：需要version 1的两个条目，实际{version=}, {count=}")
        first_duration, first_media = struct.unpack_from(">Qq", data, pos + 16)
        second_duration, second_media = struct.unpack_from(">Qq", data, pos + 36)
        expected = (
            round(head * movie_scale),
            0,
            round((visible_duration - head) * movie_scale),
            round((head + hidden) * media_scale),
        )
        actual = (first_duration, first_media, second_duration, second_media)
        tolerances = (1, 0, 1, 1)
        if any(abs(a - e) > t for a, e, t in zip(actual, expected, tolerances)):
            raise RuntimeError(f"编辑列表校验失败：{actual=}，{expected=}")


def encode_standard(source, output, duration=None, stop_event=None, width=720, height=1280):
    source_duration, has_audio = video_info(source)
    args = [FFMPEG, "-y", "-nostdin", "-hide_banner", "-loglevel", "error"]
    if duration:
        args += ["-stream_loop", "-1"]
    args += ["-i", source]
    if not has_audio:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    vf = (
        f"setsar=1,scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30:round=near,"
        "format=yuv420p,setsar=1"
    )
    args += [
        "-vf", vf, "-vsync", "cfr", "-r", "30", "-map", "0:v:0",
        "-map", "0:a:0" if has_audio else "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-ac", "2", "-ar", "44100",
    ]
    if duration:
        args += ["-t", str(duration)]
    args.append(output)
    run(args, stop_event)
    return source_duration


def butterfly_ab(
    main, auxiliary, output, head=0.3, hidden=None, use_gpu=False,
    log_callback=None, progress_callback=None, stop_event=None,
    width=720, height=1280,
):
    log = log_callback or (lambda _: None)
    progress = progress_callback or (lambda _: None)
    duration, _ = video_info(main)
    if not 0 < head < duration:
        raise ValueError("head 必须大于 0 且小于主视频时长")
    hidden = duration + 0.0667 if hidden is None else hidden
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hdh_hb_") as folder:
        folder = Path(folder)
        a_std, b_full = folder / "A_std.mp4", folder / "B_full.mp4"
        log("阶段 1/3：标准化主视频 A")
        progress(10)
        encode_standard(main, a_std, stop_event=stop_event, width=width, height=height)
        log("阶段 2/3：生成23秒辅助视频 B 块")
        progress(35)
        encode_standard(auxiliary, b_full, 23, stop_event, width, height)

        chunk_durations = [23.0] * int(hidden // 23)
        if hidden - sum(chunk_durations) > 0.02:
            chunk_durations.append(hidden - sum(chunk_durations))
        inputs = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", a_std]
        for _ in chunk_durations:
            inputs += ["-i", b_full]

        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30:round=near,"
            "format=yuv420p,setsar=1"
        )
        filters = [
            f"[0:v]trim=0:{head},setpts=PTS-STARTPTS,{vf}[v0]",
            f"[0:a]atrim=0:{head},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo[a0]",
        ]
        concat_v, concat_a = ["[v0]"], ["[a0]"]
        for i, chunk in enumerate(chunk_durations, 1):
            filters += [
                f"[{i}:v]trim=0:{chunk:.4f},setpts=PTS-STARTPTS,{vf}[vb{i}]",
                f"[{i}:a]atrim=0:{chunk:.4f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_rates=44100:channel_layouts=stereo[ab{i}]",
            ]
            concat_v.append(f"[vb{i}]")
            concat_a.append(f"[ab{i}]")
        tail = len(chunk_durations) + 1
        filters += [
            f"[0:v]trim=start={head},setpts=PTS-STARTPTS,{vf}[v{tail}]",
            f"[0:a]atrim=start={head},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo[a{tail}]",
        ]
        concat_v.append(f"[v{tail}]")
        concat_a.append(f"[a{tail}]")
        n = len(concat_v)
        filters += [
            f"{''.join(concat_v)}concat=n={n}:v=1:a=0[v]",
            f"{''.join(concat_a)}concat=n={n}:v=0:a=1[a]",
        ]
        jump_frame = round((head + hidden) * 30)
        main_frames = round(duration * 30)
        enc = (
            ["-c:v", "h264_nvenc", "-forced-idr", "1", "-bf", "0", "-rc", "cbr",
             "-b:v", "2160k", "-maxrate", "2160k", "-bufsize", "4320k",
             "-g", str(max(30, main_frames))]
            if use_gpu else
            ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
        )
        log(f"阶段 3/3：合成并隐藏 {hidden:.4f} 秒 B 段")
        progress(55)
        run(inputs + [
            "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
            "-vsync", "cfr", "-r", "30", "-force_key_frames:v",
            f"expr:eq(n,0)+eq(n,{jump_frame})+eq(n,{main_frames})",
        ] + enc + [
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100", output,
        ], stop_event)
    log("封装优化：写入 MP4 编辑列表")
    progress(90)
    hide_middle(output, duration, head, hidden)
    validate_edit_lists(output, duration, head, hidden)
    reported = float(probe(output)["format"]["duration"])
    if abs(reported - duration) > 0.15:
        raise RuntimeError(
            f"编辑列表校验失败：主视频 {duration:.3f}s，输出识别为 {reported:.3f}s"
        )
    progress(100)
    log(f"封装校验通过：平台识别时长 {reported:.3f} 秒")
    log("处理完成")
    return output


def process_batch(config, base_dir, log_callback=None, progress_callback=None, stop_event=None):
    """Use the app's folders and batch settings for Butterfly AB."""
    from engine.ffmpeg_builder import VIDEO_EXTS, list_media

    resolve = lambda value: Path(value) if Path(value).is_absolute() else base_dir / value
    mains = list_media(str(resolve(config.ab_main_folder)), VIDEO_EXTS)
    auxiliaries = list_media(str(resolve(config.ab_auxiliary_folder)), VIDEO_EXTS)
    output_folder = resolve(config.ab_output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    if not mains or not auxiliaries:
        (log_callback or print)("[错误] 主素材或辅助视频文件夹中没有视频")
        return False

    width, height = map(int, config.ab_resolution.split("x"))
    total = len(mains) * config.ab_repeat_count
    failed = 0
    for main in mains:
        for repeat in range(config.ab_repeat_count):
            if stop_event and stop_event.is_set():
                return False
            auxiliary = random.choice(auxiliaries)
            suffix = f"_{repeat + 1}" if config.ab_repeat_count > 1 else ""
            output = output_folder / f"{main.stem}{suffix}_蝴蝶AB.mp4"
            job = len(mains[:mains.index(main)]) * config.repeat_count + repeat + 1
            (log_callback or print)(
                f"\n━━━ 蝴蝶AB [{job}/{total}]: {main.name} + {auxiliary.name} ━━━"
            )
            try:
                butterfly_ab(
                    main, auxiliary, output, use_gpu=config.ab_gpu,
                    log_callback=log_callback,
                    progress_callback=(
                        (lambda value, j=job: progress_callback((j - 1) * 100 + value, total * 100))
                        if progress_callback else None
                    ),
                    stop_event=stop_event, width=width, height=height,
                )
                if config.ab_delete_used_aux:
                    auxiliary.unlink()
                    auxiliaries.remove(auxiliary)
                    if not auxiliaries and job < total:
                        raise RuntimeError("可用辅助视频已耗尽")
            except InterruptedError:
                return False
            except Exception as error:
                failed += 1
                (log_callback or print)(f"[失败] {error}")
    (log_callback or print)(f"\n══════ 蝴蝶AB结束，成功 {total - failed}，失败 {failed} ══════")
    return failed == 0


def self_test(use_gpu=False):
    with tempfile.TemporaryDirectory(prefix="butterfly_ab_") as folder:
        folder = Path(folder)
        a, b = folder / "a.mp4", folder / "b.mp4"
        out, transcoded = folder / "out.mp4", folder / "transcoded.mp4"
        for path, color, tone, seconds in ((a, "red", 440, 4), (b, "blue", 880, 2)):
            run([
                FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color={color}:s=360x640:d={seconds}",
                "-f", "lavfi", "-i", f"sine={tone}:d={seconds}",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
            ])
        butterfly_ab(a, b, out, use_gpu=use_gpu)
        got = float(probe(out)["format"]["duration"])
        assert abs(got - 4) < 0.1, (got, "编辑列表未生效")

        def pixel(path, ignore_editlist=False, second=1):
            cmd = [str(FFMPEG), "-hide_banner", "-loglevel", "error"]
            if ignore_editlist:
                cmd += ["-ignore_editlist", "1"]
            cmd += [
                "-ss", str(second), "-i", str(path), "-frames:v", "1",
                "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ]
            return tuple(subprocess.run(cmd, check=True, capture_output=True).stdout[:3])

        visible = pixel(out)
        physical = pixel(out, True)
        assert visible[0] > visible[2] * 2, ("正常播放没有得到主视频A", visible)
        assert physical[2] > physical[0] * 2, ("物理媒体中没有辅助视频B", physical)

        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", out,
            "-c:v", "libx264", "-c:a", "aac", transcoded,
        ])
        after_transcode = pixel(transcoded)
        assert after_transcode[0] > after_transcode[2] * 2, (
            "按编辑列表转码后没有得到主视频A", after_transcode,
        )

        # 跨过23秒分块边界，并覆盖“辅助视频无音轨自动补静音”。
        long_a, silent_b, long_out = (
            folder / "long_a.mp4", folder / "silent_b.mp4", folder / "long_out.mp4"
        )
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=red:s=180x320:d=25",
            "-f", "lavfi", "-i", "sine=440:d=25",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", long_a,
        ])
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=blue:s=180x320:d=2",
            "-c:v", "libx264", silent_b,
        ])
        butterfly_ab(
            long_a, silent_b, long_out, use_gpu=use_gpu, width=180, height=320
        )
        long_duration = float(probe(long_out)["format"]["duration"])
        long_visible = pixel(long_out, second=20)
        long_physical = pixel(long_out, True, 24)
        assert abs(long_duration - 25) < 0.1
        assert long_visible[0] > long_visible[2] * 2
        assert long_physical[2] > long_physical[0] * 2
        print(
            "self-test OK:",
            f"encoder={'GPU' if use_gpu else 'CPU'}",
            f"duration={got:.3f}s",
            f"visible_A={visible}",
            f"physical_B={physical}",
            f"transcoded_A={after_transcode}",
            f"23s_boundary=OK",
            f"silent_audio=OK",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("main", nargs="?")
    parser.add_argument("auxiliary", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--head", type=float, default=0.3)
    parser.add_argument("--hidden", type=float)
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(args.gpu)
    elif not all((args.main, args.auxiliary, args.output)):
        parser.error("需要 main auxiliary output，或使用 --self-test")
    else:
        print(butterfly_ab(
            args.main, args.auxiliary, args.output, args.head, args.hidden, args.gpu
        ))
