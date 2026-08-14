"""黑猫03：SPH34 后置稀疏时间轴，不包含前置跳秒处理。"""

from __future__ import annotations

import random
import time
from pathlib import Path

from engine.butterfly_ab import FFMPEG, _probe_duration, _run_ffmpeg, gpu_encoder
from engine.ffmpeg_builder import VIDEO_EXTS, list_media
from engine.output_naming import output_name


INSERT_INTERVAL = 30.0
INSERT_DURATION = 0.1
TAIL_DURATION = 1.0


def build_sph34_sparse_command(
    main: Path,
    auxiliary: Path,
    output: Path,
    width: int,
    height: int,
    main_duration: float,
    auxiliary_duration: float,
    encoder: str | None = None,
    *,
    insert_interval: float = INSERT_INTERVAL,
    insert_duration: float = INSERT_DURATION,
    tail_duration: float = TAIL_DURATION,
    rng: random.Random | None = None,
) -> list:
    """构造 A + 稀疏 B 片段 + B 尾段的 SPH34 命令。"""
    if main_duration <= 0:
        raise ValueError("无法读取主视频 A 的时长")
    if auxiliary_duration < tail_duration:
        raise ValueError(f"辅助视频 B 必须至少 {tail_duration:g} 秒")
    if insert_interval <= 0 or insert_duration < 0 or tail_duration <= 0:
        raise ValueError("SPH34 时间轴参数无效")

    randomizer = rng or random.Random()
    tail_start = auxiliary_duration - tail_duration
    target_points: list[float] = []
    point = insert_interval
    while insert_duration > 0 and point + insert_duration < tail_start:
        target_points.append(point)
        point += insert_interval

    sample_limit = max(0.0, tail_start - insert_duration)
    sample_points: list[float] = []
    for _ in target_points:
        candidate = randomizer.uniform(0.0, sample_limit) if sample_limit else 0.0
        for _attempt in range(20):
            if all(abs(candidate - old) >= insert_duration for old in sample_points):
                break
            candidate = randomizer.uniform(0.0, sample_limit) if sample_limit else 0.0
        sample_points.append(candidate)

    fit = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    )
    graph = [
        f"[0:v]{fit},setpts=PTS-STARTPTS[av]",
        "[0:a]asetpts=PTS-STARTPTS[aa]",
    ]
    video_inputs = ["[av]"]
    source_offsets = [0.0]
    target_offsets = [0.0]
    consumed = main_duration

    for index, (target_point, sample_point) in enumerate(zip(target_points, sample_points)):
        graph.append(
            f"[1:v]trim=start={sample_point:.6f}:duration={insert_duration:.6f},"
            f"setpts=PTS-STARTPTS,{fit}[iv{index}]"
        )
        video_inputs.append(f"[iv{index}]")
        source_offsets.append(consumed)
        target_offsets.append(main_duration + target_point)
        consumed += insert_duration

    graph.extend([
        f"[1:v]trim=start={tail_start:.6f}:duration={tail_duration:.6f},"
        f"setpts=PTS-STARTPTS,{fit}[bv]",
        f"[1:a]atrim=start={tail_start:.6f}:duration={tail_duration:.6f},"
        "asetpts=PTS-STARTPTS[ba]",
    ])
    video_inputs.append("[bv]")
    source_offsets.append(consumed)
    target_offsets.append(main_duration + tail_start)

    graph.append("".join(video_inputs) + f"concat=n={len(video_inputs)}:v=1:a=0[packedv]")
    graph.append("[aa][ba]concat=n=2:v=0:a=1[packeda]")

    def sparse_pts(sources: list[float], targets: list[float]) -> str:
        expression = "PTS"
        for source, target in zip(sources[1:], targets[1:]):
            shift = target - source
            expression = (
                f"if(gte(PTS-STARTPTS,{source:.6f}/TB),"
                f"PTS+{shift:.6f}/TB,{expression})"
            )
        return expression

    graph.append(
        f"[packedv]setpts='{sparse_pts(source_offsets, target_offsets)}',"
        "format=yuv420p[outv]"
    )
    audio_pts = sparse_pts(
        [0.0, main_duration],
        [0.0, main_duration + tail_start],
    )
    graph.append(f"[packeda]asetpts='{audio_pts}'[outa]")

    video_args = (
        ["-c:v", encoder, "-b:v", "5000k", "-maxrate", "5000k", "-bufsize", "10000k"]
        if encoder else ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    )
    return [
        FFMPEG, "-y", "-nostdin", "-hide_banner", "-loglevel", "info", "-stats",
        "-i", main, "-i", auxiliary,
        "-filter_complex", ";".join(graph),
        "-map", "[outv]", "-map", "[outa]", *video_args,
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-metadata", "BaseAlgorithm=SPH34", output,
    ]


def process_batch(config, base_dir, log_callback=None, progress_callback=None,
                  stop_event=None, task_callback=None, task_scope_provider=None):
    """批量执行不含前置跳秒的 SPH34 稀疏时间轴通道。"""
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
            if not auxiliaries:
                log("[失败] 辅助视频 B 已用完")
                return False
            job += 1
            auxiliary = random.choice(auxiliaries)
            output = output_folder / output_name(main)
            if config.ab_repeat_count > 1:
                output = output.with_stem(f"{output.stem}_{repeat + 1}")
            task_callback and task_callback({
                "channel": "blackcat03", "main": main, "background": auxiliary,
            })
            log(f"\n━━━ 黑猫03·SPH34 [{job}/{total}]: {main.name} + {auxiliary.name} ━━━")
            try:
                if not task_scope_provider:
                    raise RuntimeError("缺少服务器签名任务令牌")
                task_scope_provider()
                main_duration = _probe_duration(main)
                auxiliary_duration = _probe_duration(auxiliary)
                command = build_sph34_sparse_command(
                    main, auxiliary, output, width, height,
                    main_duration, auxiliary_duration,
                    gpu_encoder() if config.ab_gpu else None,
                    insert_duration=float(getattr(config, "ab_insert_duration", INSERT_DURATION)),
                )
                _run_ffmpeg(
                    command, main_duration + auxiliary_duration,
                    progress_callback=lambda frac, n=job: progress_callback and
                        progress_callback(int(((n - 1) + frac) * 1000), total * 1000),
                    stop_event=stop_event,
                )
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
    log(
        f"\n══════ 黑猫03·SPH34结束，成功 {total-failed}，失败 {failed}，"
        f"耗时 {elapsed:.0f}秒 ══════"
    )
    return failed == 0
