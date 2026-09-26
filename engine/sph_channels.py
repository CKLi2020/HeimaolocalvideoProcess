"""黑猫02：SPH34 的 B+A+B 单轨兼容实现。"""

from __future__ import annotations

import random
import struct
import time
from pathlib import Path

from engine.butterfly_ab import (
    FFMPEG, _probe_duration, _run_ffmpeg, box, boxes, children, gpu_encoder,
    patch_duration, shift_chunk_offsets, track_timescale,
)
from engine.ffmpeg_builder import VIDEO_EXTS, list_media
from engine.output_naming import output_name


def _middle_edit_list(movie_scale: int, media_scale: int, duration: float,
                      media_start: float) -> bytes:
    entry = struct.pack(">Qqhh", round(duration * movie_scale),
                        round(media_start * media_scale), 1, 0)
    return box(b"edts", box(b"elst", b"\x01\x00\x00\x00" + struct.pack(">I", 1) + entry))


def hide_sph34_edges(path: Path, main_duration: float, edge: float = 0.1) -> None:
    """保留物理 B+A+B，使用 MP4 编辑列表让正常播放只显示中间 A。"""
    data = path.read_bytes()
    top = list(boxes(data))
    moov = next(item for item in top if item[2] == b"moov")
    mdat = next(item for item in top if item[2] == b"mdat")
    mvhd = next(item for item in children(data, moov) if item[2] == b"mvhd")
    new_mvhd, movie_scale = patch_duration(
        data[mvhd[0]:mvhd[0] + mvhd[1]], b"mvhd", main_duration
    )
    rebuilt = []
    for child in children(data, moov):
        pos, size, kind, _ = child
        if kind == b"mvhd":
            rebuilt.append(new_mvhd)
        elif kind != b"trak":
            rebuilt.append(data[pos:pos + size])
        else:
            media_scale = track_timescale(data, child)
            parts = []
            inserted = False
            for item in children(data, child):
                p, n, k, _ = item
                if k == b"tkhd":
                    patched, _ = patch_duration(
                        data[p:p + n], b"tkhd", main_duration, movie_scale
                    )
                    parts.append(patched)
                elif k == b"edts":
                    parts.append(_middle_edit_list(
                        movie_scale, media_scale, main_duration, edge
                    ))
                    inserted = True
                else:
                    parts.append(data[p:p + n])
                    if k == b"mdia" and not inserted:
                        parts.insert(-1, _middle_edit_list(
                            movie_scale, media_scale, main_duration, edge
                        ))
                        inserted = True
            rebuilt.append(box(b"trak", b"".join(parts)))
    new_moov = box(b"moov", b"".join(rebuilt))
    if moov[0] < mdat[0]:
        new_moov = shift_chunk_offsets(new_moov, len(new_moov) - moov[1])
    path.write_bytes(data[:moov[0]] + new_moov + data[moov[0] + moov[1]:])


def build_sph34_command(main: Path, auxiliary: Path, output: Path,
                        width: int, height: int,
                        encoder: str | None = None) -> list:
    edge = 0.1
    fit_b = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30"
    )
    fit_a = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    )
    graph = (
        f"[1:v]trim=0:{edge},setpts=PTS-STARTPTS,{fit_b}[b0];"
        f"[0:v]setpts=PTS-STARTPTS,{fit_a}[a];"
        f"[1:v]trim=start={edge}:duration={edge},setpts=PTS-STARTPTS,{fit_b}[b1];"
        "[b0][a][b1]concat=n=3:v=1:a=0,format=yuv420p[outv];"
        f"[1:a]atrim=0:{edge},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[ba0];"
        "[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[aa];"
        f"[1:a]atrim=start={edge}:duration={edge},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[ba1];"
        "[ba0][aa][ba1]concat=n=3:v=0:a=1[outa]"
    )
    video = (
        ["-c:v", encoder, "-b:v", "5000k", "-maxrate", "5000k", "-bufsize", "10000k"]
        if encoder else ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    )
    return [
        FFMPEG, "-y", "-nostdin", "-hide_banner", "-loglevel", "info", "-stats",
        "-i", main, "-stream_loop", "-1", "-i", auxiliary,
        "-filter_complex", graph, "-map", "[outv]", "-map", "[outa]", *video,
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-metadata", "BaseAlgorithm=SPH34", output,
    ]


def process_batch(config, base_dir, log_callback=None, progress_callback=None,
                  stop_event=None, task_callback=None):
    log = log_callback or print
    resolve = lambda value: Path(value) if Path(value).is_absolute() else base_dir / value
    mains = list_media(str(resolve(config.ab_main_folder)), VIDEO_EXTS)
    auxiliaries = list_media(str(resolve(config.ab_auxiliary_folder)), VIDEO_EXTS)
    output_folder = resolve(config.ab_output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    if not mains or not auxiliaries:
        log("[错误] 主素材或辅助视频文件夹中没有视频")
        return False
    total = len(mains) * config.ab_repeat_count
    width, height = map(int, config.ab_resolution.split("x"))
    failed = 0
    started = time.time()
    job = 0
    for main in mains:
        for repeat in range(config.ab_repeat_count):
            if stop_event and stop_event.is_set():
                return False
            job += 1
            auxiliary = random.choice(auxiliaries)
            output = output_folder / output_name(main)
            if config.ab_repeat_count > 1:
                output = output.with_stem(f"{output.stem}_{repeat + 1}")
            task_callback and task_callback({
                "channel": "blackcat02", "main": main, "background": auxiliary,
            })
            log(f"\n━━━ 黑猫02·蝴蝶AB [{job}/{total}]: {main.name} + {auxiliary.name} ━━━")
            try:
                encoder = gpu_encoder() if config.ab_gpu else None
                duration = _probe_duration(main)
                command = build_sph34_command(
                    main, auxiliary, output, width, height, encoder
                )
                _run_ffmpeg(
                    command, duration + 0.2,
                    progress_callback=lambda frac, n=job: progress_callback and
                        progress_callback(int(((n - 1) + frac) * 1000), total * 1000),
                    stop_event=stop_event,
                )
                hide_sph34_edges(output, duration)
                if config.ab_delete_used_aux:
                    auxiliary.unlink()
                    auxiliaries.remove(auxiliary)
            except InterruptedError:
                return False
            except Exception as error:
                failed += 1
                log(f"[失败] {error}")
            progress_callback and progress_callback(job * 1000, total * 1000)
    elapsed = time.time() - started
    log(f"\n══════ 黑猫02·蝴蝶AB结束，成功 {total-failed}，失败 {failed}，耗时 {elapsed:.0f}秒 ══════")
    return failed == 0
