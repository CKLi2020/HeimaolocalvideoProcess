"""2026-08-01 蝴蝶AB：媒体内 A头+B+A尾，MP4 编辑列表播放时跳过 B。
Phase 2: 真实进度条 —— 解析 ffmpeg time= 输出。
"""

import argparse
from functools import lru_cache
import json
import random
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time as _time_module
from pathlib import Path

from engine.output_naming import output_name
from engine import HIDDEN_SUBPROCESS
from app._flowcut_core import authorized_butterfly_plan

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


@lru_cache(maxsize=1)
def gpu_encoder():
    """选择本机实际可用的 H.264 GPU 编码器。"""
    for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
        result = subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
                "-frames:v", "1", "-an", "-c:v", encoder, "-f", "null", "-",
            ],
            capture_output=True, timeout=10,
            **HIDDEN_SUBPROCESS,
        )
        if result.returncode == 0:
            return encoder
    return None


def _probe_duration(path) -> float:
    """用 ffprobe 获取视频时长（秒）。"""
    try:
        result = subprocess.run(
            [str(FFPROBE), "-v", "error", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20,
            **HIDDEN_SUBPROCESS,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info["format"].get("duration", 0))
    except Exception:
        pass
    return 0.0


def _run_ffmpeg(
    cmd: list,
    duration: float,
    progress_callback=None,
    stop_event=None,
) -> subprocess.CompletedProcess:
    """运行 ffmpeg，从 stderr 解析 time= 获得真实编码进度。

    Args:
        cmd: ffmpeg 命令行
        duration: 预期输出时长（秒）
        progress_callback: 进度回调 0.0~1.0
        stop_event: 取消事件

    Returns:
        CompletedProcess
    """
    process = subprocess.Popen(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        **HIDDEN_SUBPROCESS,
    )

    time_re = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
    stderr_lines: list[str] = []
    _last_frac = 0.0

    def _reader() -> None:
        nonlocal _last_frac
        try:
            for line in process.stderr:  # type: ignore[union-attr]
                stderr_lines.append(line)
                if duration <= 0:
                    continue
                m = time_re.search(line)
                if m:
                    h, mi, s, cs = map(int, m.groups())
                    current = h * 3600 + mi * 60 + s + cs / 100.0
                    frac = min(current / duration, 0.98)
                    if frac > _last_frac + 0.005 and progress_callback:
                        _last_frac = frac
                        progress_callback(frac)
        except Exception:
            pass

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    import time as _time
    try:
        while process.poll() is None:
            if stop_event and stop_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                reader.join(timeout=2)
                raise InterruptedError("用户已停止处理")
            _time.sleep(0.3)
    finally:
        reader.join(timeout=2)

    if _last_frac > 0 and progress_callback:
        progress_callback(min(_last_frac + 0.02, 1.0))

    if process.returncode and process.returncode != 0:
        stderr = "".join(stderr_lines)
        raise subprocess.CalledProcessError(process.returncode, cmd, stderr=stderr)

    return subprocess.CompletedProcess(cmd, process.returncode, "", "")


def run(cmd, stop_event=None):
    """向后兼容：无进度的快速 ffmpeg 调用。"""
    process = subprocess.Popen([str(x) for x in cmd], **HIDDEN_SUBPROCESS)
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
        **HIDDEN_SUBPROCESS,
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


def encode_standard(source, output, duration=None, stop_event=None, width=720, height=1280,
                    progress_callback=None, video_encoder=None):
    """标准化视频编码，支持真实进度回调。"""
    source_duration, has_audio = video_info(source)
    args = [FFMPEG, "-y", "-nostdin", "-hide_banner", "-loglevel", "info", "-stats"]
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
    ]
    args += (
        ["-c:v", video_encoder, "-b:v", "2160k", "-maxrate", "2160k",
         "-bufsize", "4320k", "-pix_fmt", "yuv420p"]
        if video_encoder else
        ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
         "-pix_fmt", "yuv420p"]
    )
    args += [
        "-c:a", "aac", "-b:a", "96k",
        "-ac", "2", "-ar", "44100",
    ]
    if duration:
        args += ["-t", str(duration)]
    args.append(output)

    real_duration = duration if duration else source_duration
    _run_ffmpeg(args, real_duration, progress_callback=progress_callback, stop_event=stop_event)
    return source_duration


def butterfly_ab(
    main, auxiliary, output, head=0.3, hidden=None, use_gpu=False,
    log_callback=None, progress_callback=None, stop_event=None,
    width=720, height=1280, task_scope=None,
):
    """蝴蝶AB：A头+B段+A尾，通过编辑列表让平台跳过B。

    progress_callback: 每个阶段调用，传入 0.0~1.0 的真实进度。
    """
    log = log_callback or (lambda _: None)
    progress = progress_callback or (lambda _: None)
    encoder = gpu_encoder() if use_gpu else None
    if use_gpu:
        log(f"  GPU 编码器: {encoder or '不可用，使用 CPU'}")

    duration, _ = video_info(main)
    if not 0 < head < duration:
        raise ValueError("head 必须大于 0 且小于主视频时长")
    if not task_scope:
        raise RuntimeError("缺少服务器签名任务令牌")
    plan = authorized_butterfly_plan(
        task_scope["token"], task_scope["engine"],
        task_scope["batch_id"], task_scope["input_count"],
        task_scope["params_hash"], task_scope["device_code"],
        task_scope["device_fingerprint"],
        duration, head, hidden, 30,
    )
    hidden = plan["hidden"]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    # 预估总工作量：编码主视频(主时长) + 编码辅助(23s) + 拼接(主时长+隐藏) + 封装(快)
    # 权重：阶段1=30%, 阶段2=15%, 阶段3=50%, 阶段4=5%
    total_work = duration + 23.0 + (duration + hidden) + 1.0
    w1 = duration / total_work
    w2 = 23.0 / total_work
    w3 = (duration + hidden) / total_work
    w4 = 1.0 / total_work

    with tempfile.TemporaryDirectory(prefix="hdh_hb_") as folder:
        folder = Path(folder)
        a_std, b_full = folder / "A_std.mp4", folder / "B_full.mp4"

        log("  编码主视频...")

        def _stage1(frac: float) -> None:
            progress(w1 * frac)

        encode_standard(
            main, a_std,
            stop_event=stop_event, width=width, height=height,
            progress_callback=_stage1, video_encoder=encoder,
        )

        log("  编码辅助视频...")

        def _stage2(frac: float) -> None:
            progress(w1 + w2 * frac)

        encode_standard(
            auxiliary, b_full, 23,
            stop_event=stop_event, width=width, height=height,
            progress_callback=_stage2, video_encoder=encoder,
        )

        chunk_durations = plan["chunks"]
        inputs = [FFMPEG, "-y", "-hide_banner", "-loglevel", "info", "-stats", "-i", a_std]
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
        tail_idx = len(chunk_durations) + 1
        filters += [
            f"[0:v]trim=start={head},setpts=PTS-STARTPTS,{vf}[v{tail_idx}]",
            f"[0:a]atrim=start={head},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo[a{tail_idx}]",
        ]
        concat_v.append(f"[v{tail_idx}]")
        concat_a.append(f"[a{tail_idx}]")
        n = len(concat_v)
        filters += [
            f"{''.join(concat_v)}concat=n={n}:v=1:a=0[v]",
            f"{''.join(concat_a)}concat=n={n}:v=0:a=1[a]",
        ]
        jump_frame = plan["jump_frame"]
        main_frames = plan["main_frames"]
        enc = (
            ["-c:v", encoder, "-bf", "0",
             "-b:v", "2160k", "-maxrate", "2160k", "-bufsize", "4320k",
             "-g", str(max(30, main_frames))]
            if encoder else
            ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
        )

        log("  合成拼接...")

        def _stage3(frac: float) -> None:
            progress(w1 + w2 + w3 * frac)

        _run_ffmpeg(
            inputs + [
                "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                "-vsync", "cfr", "-r", "30", "-force_key_frames:v",
                f"expr:eq(n,0)+eq(n,{jump_frame})+eq(n,{main_frames})",
            ] + enc + [
                "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100", str(output),
            ],
            duration + hidden,  # 拼接输出时长
            progress_callback=_stage3,
            stop_event=stop_event,
        )

    log("  写入编辑列表...")
    progress(w1 + w2 + w3)
    hide_middle(output, duration, head, hidden)
    validate_edit_lists(output, duration, head, hidden)
    reported = float(probe(output)["format"]["duration"])
    if abs(reported - duration) > 0.15:
        raise RuntimeError(
            f"编辑列表校验失败：主视频 {duration:.3f}s，输出识别为 {reported:.3f}s"
        )
    progress(1.0)
    log("  校验通过")
    return output


def process_batch(
    config, base_dir, log_callback=None, progress_callback=None,
    stop_event=None, task_callback=None, task_scope_provider=None,
):
    """使用 App 的文件夹和批量设置执行蝴蝶 AB 批量处理（含真实进度）。"""
    from engine.ffmpeg_builder import VIDEO_EXTS, list_media

    _start_time = _time_module.time()
    if not task_scope_provider:
        raise RuntimeError("缺少服务器签名任务令牌")

    resolve = lambda value: Path(value) if Path(value).is_absolute() else base_dir / value
    mains = list_media(str(resolve(config.ab_main_folder)), VIDEO_EXTS)
    auxiliaries = list_media(str(resolve(config.ab_auxiliary_folder)), VIDEO_EXTS)
    output_folder = resolve(config.ab_output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    if not mains or not auxiliaries:
        (log_callback or print)("[错误] 主素材或辅助视频文件夹中没有视频")
        return False

    # ── 预扫描视频时长，计算总工作量 ──
    # 预扫描视频时长（静默）
    main_durations = {}
    total_work = 0.0
    for mv in mains:
        dur = _probe_duration(mv)
        main_durations[str(mv)] = max(dur, 0.5)
        # 每个视频工作量 ≈ 编码主视频(主时长) + 编码辅助(23s) + 拼接(时长+隐藏) + 封装
        hidden = dur + 0.0667
        total_work += (dur + 23.0 + (dur + hidden) + 1.0) * config.ab_repeat_count

    if total_work <= 0:
        total_work = float(len(mains) * config.ab_repeat_count)

    # 已分析完成

    total_jobs = len(mains) * config.ab_repeat_count
    width, height = map(int, config.ab_resolution.split("x"))
    failed = 0
    cumulative_work = 0.0

    for main_idx, main in enumerate(mains):
        main_dur = main_durations[str(main)]
        for repeat in range(config.ab_repeat_count):
            if stop_event and stop_event.is_set():
                return False

            auxiliary = random.choice(auxiliaries)
            suffix = f"_{repeat + 1}" if config.ab_repeat_count > 1 else ""
            output = output_folder / output_name(main)
            job = main_idx * config.ab_repeat_count + repeat + 1

            if task_callback:
                task_callback({
                    "channel": "butterfly_ab",
                    "main": main,
                    "background": auxiliary,
                })
            (log_callback or print)(
                f"\n━━━ 蝴蝶AB [{job}/{total_jobs}]: {main.name} + {auxiliary.name} ━━━"
            )

            # 当前 job 的工作量
            hidden = main_dur + 0.0667
            job_work = main_dur + 23.0 + (main_dur + hidden) + 1.0

            def _make_progress(base_work: float, job_w: float):
                def _report(frac: float) -> None:
                    if progress_callback:
                        current = base_work + job_w * frac
                        progress_callback(int(current * 1000), int(total_work * 1000))
                return _report

            job_progress = _make_progress(cumulative_work, job_work)

            try:
                task_scope = task_scope_provider()
                butterfly_ab(
                    main, auxiliary, output, use_gpu=config.ab_gpu,
                    log_callback=log_callback,
                    progress_callback=job_progress,
                    stop_event=stop_event, width=width, height=height,
                    task_scope=task_scope,
                )
                if config.ab_delete_used_aux:
                    auxiliary.unlink()
                    auxiliaries.remove(auxiliary)
                    if not auxiliaries and job < total_jobs:
                        raise RuntimeError("可用辅助视频已耗尽")
            except InterruptedError:
                return False
            except Exception as error:
                failed += 1
                (log_callback or print)(f"[失败] {error}")

            cumulative_work += job_work
            if progress_callback:
                progress_callback(int(cumulative_work * 1000), int(total_work * 1000))

    # 确保 100%
    if progress_callback:
        progress_callback(int(total_work * 1000), int(total_work * 1000))

    _elapsed = _time_module.time() - _start_time
    _elapsed_str = f"{int(_elapsed // 60)}分{int(_elapsed % 60)}秒" if _elapsed >= 60 else f"{_elapsed:.0f}秒"
    (log_callback or print)(f"\n══════ 蝴蝶AB结束，成功 {total_jobs - failed}，失败 {failed}，耗时 {_elapsed_str} ══════")
    return failed == 0


def self_test(use_gpu=False):
    with tempfile.TemporaryDirectory(prefix="butterfly_ab_") as folder:
        folder = Path(folder)
        a, b = folder / "a.mp4", folder / "b.mp4"
        out, transcoded = folder / "out.mp4", folder / "transcoded.mp4"
        for path, color, tone, seconds in ((a, "red", 440, 4), (b, "blue", 880, 2)):
            _run_ffmpeg([
                FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color={color}:s=360x640:d={seconds}",
                "-f", "lavfi", "-i", f"sine={tone}:d={seconds}",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
            ], seconds)
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
            return tuple(subprocess.run(
                cmd, check=True, capture_output=True, **HIDDEN_SUBPROCESS
            ).stdout[:3])

        visible = pixel(out)
        physical = pixel(out, True)
        assert visible[0] > visible[2] * 2, ("正常播放没有得到主视频A", visible)
        assert physical[2] > physical[0] * 2, ("物理媒体中没有辅助视频B", physical)

        _run_ffmpeg([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", out,
            "-c:v", "libx264", "-c:a", "aac", transcoded,
        ], got)
        after_transcode = pixel(transcoded)
        assert after_transcode[0] > after_transcode[2] * 2, (
            "按编辑列表转码后没有得到主视频A", after_transcode,
        )

        long_a, silent_b, long_out = (
            folder / "long_a.mp4", folder / "silent_b.mp4", folder / "long_out.mp4"
        )
        _run_ffmpeg([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=red:s=180x320:d=25",
            "-f", "lavfi", "-i", "sine=440:d=25",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", long_a,
        ], 25)
        _run_ffmpeg([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=blue:s=180x320:d=2",
            "-c:v", "libx264", silent_b,
        ], 2)
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
