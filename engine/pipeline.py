"""批量处理管道：遍历主素材，随机选择背景/贴纸/扫光，调用 ffmpeg 合成。
Phase 2: 集成字幕识别和烧录（两遍编码）。
Phase 3: 真实进度条 —— 解析 ffmpeg time= 输出。
"""

from __future__ import annotations

import json as _json
import os
import random
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time as _time_module
from pathlib import Path
from typing import Callable, Optional

from config import AppConfig
from engine import HIDDEN_SUBPROCESS
from engine.ffmpeg_builder import (
    VIDEO_EXTS,
    IMAGE_EXTS,
    AUDIO_EXTS,
    list_media,
    pick_random,
    build_ffmpeg_command,
    build_mover_layers,
)
from engine.output_naming import output_name


def _wrap_subtitles(segments: list[dict], max_chars: int) -> list[dict]:
    """Wrap recognized text without changing timestamps."""
    width = max(1, max_chars)
    return [
        {**segment, "text": "\n".join(textwrap.wrap(segment["text"], width=width))}
        for segment in segments
    ]


def _probe_duration(path: Path) -> float:
    """用 ffprobe 获取视频时长（秒）。失败返回 0。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20,
            **HIDDEN_SUBPROCESS,
        )
        if result.returncode == 0:
            info = _json.loads(result.stdout)
            return float(info["format"].get("duration", 0))
    except Exception:
        pass
    return 0.0


def _probe_has_audio(path: Path) -> bool:
    """主素材是否含音轨；声音处理开启时每个文件只探测一次。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, **HIDDEN_SUBPROCESS,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def _estimate_voice_pitch(path: Path) -> Optional[float]:
    """估算前 30 秒对白的基频中位数（Hz）；无可靠人声时返回 None。"""
    try:
        import numpy as np

        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(path), "-t", "30",
                "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-",
            ],
            capture_output=True, timeout=40, **HIDDEN_SUBPROCESS,
        )
        if result.returncode != 0 or len(result.stdout) < 3200:
            return None
        samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
        frame_size, hop = 640, 320
        energies = np.array([
            np.mean(samples[i:i + frame_size] ** 2)
            for i in range(0, len(samples) - frame_size, hop)
        ])
        if not len(energies) or float(energies.max()) <= 0:
            return None
        energy_floor = max(float(np.percentile(energies, 60)), 1e4)
        pitches: list[float] = []
        min_lag, max_lag = 16000 // 300, 16000 // 70
        window = np.hanning(frame_size).astype(np.float32)
        for n, i in enumerate(range(0, len(samples) - frame_size, hop)):
            if n % 3 or energies[n] < energy_floor:
                continue
            frame = samples[i:i + frame_size]
            frame = (frame - frame.mean()) * window
            corr = np.correlate(frame, frame, mode="full")[frame_size - 1:]
            if corr[0] <= 0:
                continue
            lag = min_lag + int(np.argmax(corr[min_lag:max_lag + 1]))
            if corr[lag] / corr[0] >= 0.30:
                pitches.append(16000.0 / lag)
        return float(np.median(pitches)) if len(pitches) >= 3 else None
    except Exception:
        return None


def _adaptive_voice_shift(pitch_hz: Optional[float]) -> float:
    """低声线轻微提亮，高声线轻微压低；检测失败则不冒险处理。"""
    if pitch_hz is None:
        return 0.0
    return 2.0 if pitch_hz < 165.0 else -2.0


def _run_ffmpeg(
    command: list[str],
    duration: float,
    progress_callback: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Optional[subprocess.CompletedProcess]:
    """运行 ffmpeg，从 stderr 解析 time= 获得真实编码进度。

    Args:
        command: ffmpeg 命令行
        duration: 输出视频预期时长（秒），用于计算进度百分比
        progress_callback: 进度回调，参数为 0.0~1.0
        cancel_check: 返回 True 表示取消
        log: 日志回调

    Returns:
        CompletedProcess 或 None（被取消时）
    """
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        **HIDDEN_SUBPROCESS,
    )

    time_re = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
    stderr_lines: list[str] = []
    _last_frac = 0.0
    _read_done = threading.Event()

    def _read_stderr() -> None:
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
                    if frac > _last_frac + 0.005:  # 去抖动
                        _last_frac = frac
                        if progress_callback:
                            progress_callback(frac)
        except Exception:
            pass
        finally:
            _read_done.set()

    reader = threading.Thread(target=_read_stderr, daemon=True)
    reader.start()

    import time as _time
    try:
        while process.poll() is None:
            if cancel_check and cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                if log:
                    log("[取消] 已终止当前 FFmpeg")
                return None
            _time.sleep(0.3)
    finally:
        _read_done.wait(timeout=2)

    # 最后 2% 留给后续步骤
    if _last_frac > 0 and progress_callback:
        progress_callback(min(_last_frac + 0.01, 1.0))

    stderr = "".join(stderr_lines)
    return subprocess.CompletedProcess(command, process.returncode, "", stderr)


def process_batch(
    config: AppConfig,
    base_dir: Path,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    task_callback: Optional[Callable[[dict], None]] = None,
) -> bool:
    """批量处理主素材文件夹中的所有视频。

    Args:
        config: 应用配置
        base_dir: 程序根目录
        log_callback: 日志回调
        progress_callback: 进度回调 (elapsed, total) — 单位秒，反映真实编码时间
        cancel_check: 返回 True 表示取消
        task_callback: 当前任务信息回调
    """

    _start_time = _time_module.time()

    def log(msg: str) -> None:
        print(msg)
        if log_callback:
            log_callback(msg)

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else base_dir / path

    # 解析路径
    main_folder = resolve(config.main_folder)
    background_folder = resolve(config.background_folder)
    output_folder = resolve(config.output_folder)
    sticker_folder = resolve(config.sticker_folder)
    moving_sticker_folder = resolve(
        config.moving_sticker_folder or config.sticker_folder
    )
    scanlight_folder = resolve(config.scanlight_folder)
    kaimu_folder = resolve(config.kaimu_folder)
    audio_bgm_folder = resolve(config.audio_bgm_folder)

    output_folder.mkdir(parents=True, exist_ok=True)

    mains = list_media(str(main_folder), VIDEO_EXTS)
    backgrounds = list_media(str(background_folder), VIDEO_EXTS)
    background_audios = (
        list_media(str(audio_bgm_folder), AUDIO_EXTS)
        if config.audio_bgm_enabled else []
    )

    if config.audio_bgm_enabled:
        if background_audios:
            log(f"背景音乐: {len(background_audios)} 首，选自 {config.audio_bgm_folder}")
            if (
                config.audio_bgm_pick == "固定"
                and config.audio_bgm_fixed
                and not any(p.name == config.audio_bgm_fixed for p in background_audios)
            ):
                log(f"[警告] 固定音乐「{config.audio_bgm_fixed}」不在音乐库里，改为随机选择")
        else:
            log(f"[警告] 背景音乐文件夹中没有可用音频: {audio_bgm_folder}")

    # 模板模式：模板占用背景槽，所以不要求背景目录有素材。
    templates = None
    if config.tpl_enabled:
        from engine.template_lib import load_library

        templates = load_library(resolve(config.tpl_folder), config.tpl_manifest)
        if not templates:
            log(f"[错误] 模板目录中没有可用视频: {resolve(config.tpl_folder)}")
            return False
        log(f"模板: {len(templates.specs)} 个，选自 {config.tpl_folder}")
        # 固定模板没命中只提示一次，别每条任务刷一行。
        if (
            config.tpl_pick == "固定"
            and config.tpl_fixed
            and not templates.has(config.tpl_fixed)
        ):
            log(f"[警告] 固定模板「{config.tpl_fixed}」不在模板库里，改为随机选择")
    elif config.tpl_pick == "固定" and config.tpl_fixed:
        if not any(path.name == config.tpl_fixed for path in backgrounds):
            log(f"[警告] 固定辅助视频「{config.tpl_fixed}」不在素材库里，改为随机选择")

    if not mains:
        log("[错误] 主素材文件夹中没有视频文件")
        return False
    # 这里原先是「没有背景视频就整批失败」的硬校验。界面上已经没有
    # 「辅助视频文件夹」入口，留着它就成了谁也解不开的死结，所以改成放行，
    # 由下面的取背景处用纯色画布兜底（消息也在那里报，这里再报一次是重复的）。

    log(f"主素材: {len(mains)} 个, 背景视频: {len(backgrounds)} 个")

    if config.sticker_enabled:
        stickers = list_media(str(sticker_folder), VIDEO_EXTS | IMAGE_EXTS)
        log(f"贴纸: {len(stickers)} 个")
    if config.scanlight_enabled:
        scanlights = list_media(str(scanlight_folder), VIDEO_EXTS)
        log(f"扫光: {len(scanlights)} 个")
    if config.kaimu_enabled:
        kaimus = list_media(str(kaimu_folder), VIDEO_EXTS | IMAGE_EXTS)
        log(f"开幕素材: {len(kaimus)} 个")

    # ── 预扫描所有主视频时长，用于真实进度 ──
    log("正在分析视频时长...")
    main_durations: dict[str, float] = {}
    main_audio: dict[str, bool] = {}
    adaptive_pitches: dict[str, tuple[Optional[float], float]] = {}
    total_duration = 0.0
    for mv in mains:
        dur = _probe_duration(mv)
        main_durations[str(mv)] = max(dur, 0.5)  # 至少 0.5 秒防止除零
        if (
            config.audio_bgm_enabled
            or config.audio_voice_enabled
            or config.audio_voice_adaptive
        ):
            main_audio[str(mv)] = _probe_has_audio(mv)
        if config.audio_voice_adaptive and main_audio.get(str(mv), False):
            detected = _estimate_voice_pitch(mv)
            adaptive_pitches[str(mv)] = (detected, _adaptive_voice_shift(detected))
        total_duration += main_durations[str(mv)] * config.repeat_count

    if total_duration <= 0:
        # 回退：如果 ffprobe 全部失败，用文件数量作为进度单位
        total_duration = float(len(mains) * config.repeat_count)
        for mv in mains:
            main_durations[str(mv)] = 1.0

    log(f"总编码时长约 {total_duration / 60:.1f} 分钟")

    total_jobs = len(mains) * config.repeat_count
    job_index = 0
    elapsed_duration = 0.0
    failed_jobs = 0
    exhausted_logged = False

    # 进度上报：把累计秒数映射到 0~total_duration
    def _report_progress(job_duration_fraction: float = 0.0) -> None:
        if not progress_callback:
            return
        current = elapsed_duration + job_duration_fraction
        # 用整数毫秒上报，Qt 进度条更平滑
        progress_callback(int(current * 1000), int(total_duration * 1000))

    # 初始进度
    _report_progress(0.0)

    for main_video in mains:
        if cancel_check and cancel_check():
            log("[取消] 用户停止了处理")
            return False

        main_dur = main_durations[str(main_video)]
        log(f"\n━━━ 处理: {main_video.name} ({main_dur:.1f}s) ━━━")

        for repeat in range(config.repeat_count):
            if cancel_check and cancel_check():
                log("[取消] 用户停止了处理")
                return False

            job_index += 1

            background_audio = None
            if background_audios:
                fixed_audio = next(
                    (p for p in background_audios if p.name == config.audio_bgm_fixed),
                    None,
                ) if config.audio_bgm_pick == "固定" else None
                background_audio = fixed_audio or random.choice(background_audios)

            # 随机选择素材
            backgrounds = [p for p in backgrounds if p.exists()]
            template_window = None
            if templates is not None:
                # 模板即背景：替换掉普通背景槽，并按窗口几何落位主视频
                spec = templates.pick(config.tpl_pick, config.tpl_fixed)
                template_window = templates.resolve(spec, config)
                background = spec.path
            else:
                # 辅助视频是可选的：没配、目录不存在、或已被「删除已用辅助
                # 视频」消耗完，都不再把整批判失败，余下的条目走纯色画布。
                # 只在第一次报，免得每条都刷一行。
                if not backgrounds:
                    if not exhausted_logged:
                        log("  [提示] 没有可用的辅助视频，以纯色画布出片")
                        exhausted_logged = True
                    background = None
                else:
                    fixed = next(
                        (path for path in backgrounds if path.name == config.tpl_fixed),
                        None,
                    ) if config.tpl_pick == "固定" else None
                    background = fixed or random.choice(backgrounds)

            sticker_files: list[Path] = []
            if config.sticker_enabled:
                sfiles = list_media(str(sticker_folder), VIDEO_EXTS | IMAGE_EXTS)
                try:
                    layers = _json.loads(config.sticker_layers_json) if config.sticker_layers_json else []
                except Exception:
                    layers = []
                num_layers = len(layers) if layers else 1
                group_count = 2 if config.sticker_switch_sec > 0 else 1
                for _ in range(num_layers * group_count):
                    if sfiles:
                        sticker_files.append(random.choice(sfiles))

            scanlight_file = None
            if config.scanlight_enabled:
                sfiles = list_media(str(scanlight_folder), VIDEO_EXTS)
                scanlight_file = random.choice(sfiles) if sfiles else None

            kaimu_file = None
            if config.kaimu_enabled:
                kfiles = list_media(str(kaimu_folder), VIDEO_EXTS | IMAGE_EXTS)
                kaimu_file = random.choice(kfiles) if kfiles else None
                if not kaimu_file:
                    log("  [警告] 开幕素材为空，跳过开幕效果")

            mover_files: list[Path] = []
            mover_layers: Optional[list[dict]] = None
            if config.moving_sticker_enabled:
                mfiles = list_media(str(moving_sticker_folder), VIDEO_EXTS | IMAGE_EXTS)
                try:
                    mlayers = _json.loads(config.mover_layers_json) if config.mover_layers_json else []
                except Exception:
                    mlayers = []
                if not isinstance(mlayers, list):
                    mlayers = []
                # 「移动贴纸」页的数量滑条会把 mover_layers_json 同步成同样多条，
                # 正常情况两者相等；这里再取一次大者，是为了配置文件被手改过
                # （滑条说 5 个、JSON 里只有 2 条）时也照样出 5 个，不静默少出。
                num_movers = max(1, config.mover_count, len(mlayers))
                mover_layers = build_mover_layers(
                    num_movers,
                    mlayers,
                    config.mover_scale,
                    config.mover_opacity,
                    config.moving_sticker_period,
                    roll_positions=config.mover_random,
                )
                for _ in range(num_movers):
                    if mfiles:
                        mover_files.append(random.choice(mfiles))

            if task_callback:
                task_callback({
                    "main": main_video,
                    "background": background,
                    "stickers": sticker_files,
                    "scanlight": scanlight_file,
                    "kaimu": kaimu_file,
                    "movers": mover_files,
                    "mover_layers": mover_layers,
                    "template_window": template_window,
                    "background_audio": background_audio,
                })

            suffix = f"_{repeat + 1}" if config.repeat_count > 1 else ""
            output_path = output_folder / output_name(main_video)

            do_subtitle = (
                config.subtitle_enabled
                and main_video.suffix.lower() in VIDEO_EXTS
            )
            do_face_blur = (
                config.face_blur_enabled
                and main_video.suffix.lower() in VIDEO_EXTS
            )

            needs_temp = do_subtitle or do_face_blur
            compose_output = (
                output_folder / f"{main_video.stem}{suffix}_compose.mp4"
                if needs_temp else output_path
            )

            # ── 本次 job 的进度回调（0.0~1.0）──
            def _job_progress(frac: float) -> None:
                _report_progress(main_dur * frac)

            # ── Pass 1: 视频合成（主要耗时）──
            cmd = build_ffmpeg_command(
                config,
                main_video=main_video,
                background_video=background,
                output_path=compose_output,
                sticker_files=sticker_files or None,
                scanlight_file=scanlight_file,
                kaimu_file=kaimu_file,
                mover_files=mover_files or None,
                template_window=template_window,
                mover_layers=mover_layers,
                background_audio=background_audio,
                main_has_audio=main_audio.get(str(main_video), True),
                voice_pitch=(
                    adaptive_pitches.get(str(main_video), (None, 0.0))[1]
                    if config.audio_voice_adaptive else None
                ),
            )

            log(f"  [{job_index}/{total_jobs}] {main_video.stem}{suffix}")
            if background is None:
                log("    背景: 纯色画布")
            else:
                log(f"    背景: {background.name}" + ("  [模板]" if template_window else ""))
            if sticker_files:
                log(f"    贴纸: {len(sticker_files)} 层")
            if mover_files:
                # 数量与「本次位置是否重掷」都打出来：随机位置是每条片子各掷一次，
                # 不看日志的话没法确认这条片子走的是随机还是界面上那套固定走位。
                log(f"    移动贴纸: {len(mover_files)} 个"
                    + ("  [位置本次随机]" if config.mover_random else "  [位置按界面]"))
            if scanlight_file:
                log(f"    扫光: {scanlight_file.name}")
            if background_audio:
                log(f"    背景音乐: {background_audio.name} ({config.audio_bgm_volume}%)")
            if config.audio_voice_adaptive:
                detected, shift = adaptive_pitches.get(str(main_video), (None, 0.0))
                if detected is None:
                    log("    [提示] 未检测到可靠对白基频，跳过智能音色变声")
                else:
                    log(f"    智能音色变声: 基频约 {detected:.0f}Hz，自动 {shift:+.0f} 半音")
            elif config.audio_voice_enabled:
                if main_audio.get(str(main_video), True):
                    log(f"    对白变声: {config.audio_voice_pitch:+d} 半音（时长不变）")
                else:
                    log("    [提示] 主视频没有原声音轨，跳过对白变声")

            try:
                result = _run_ffmpeg(
                    cmd, main_dur,
                    progress_callback=_job_progress,
                    cancel_check=cancel_check,
                    log=log,
                )
                if result is None:
                    compose_output.unlink(missing_ok=True)
                    return False
                if result.returncode != 0 and config.gpu:
                    cpu_cmd = [
                        "libx264" if item == "h264_nvenc"
                        else "libx265" if item == "hevc_nvenc"
                        else item
                        for item in cmd
                    ]
                    log("  [GPU] 编码失败，自动回退 CPU")
                    result = _run_ffmpeg(
                        cpu_cmd, main_dur,
                        progress_callback=_job_progress,
                        cancel_check=cancel_check,
                        log=log,
                    )
                    if result is None:
                        compose_output.unlink(missing_ok=True)
                        return False
                if result.returncode != 0:
                    failed_jobs += 1
                    elapsed_duration += main_dur
                    log(f"  [失败] ffmpeg 返回码 {result.returncode}")
                    stderr_lines = result.stderr.strip().split("\n")
                    for line in stderr_lines[-15:]:
                        if line.strip():
                            log(f"    {line.strip()}")
                    _report_progress(0.0)
                    continue

                log(f"  [合成完成] {compose_output.name}")

                # ── Pass 2: 人脸模糊（可选）──
                current_video = compose_output
                if do_face_blur:
                    from engine.face_blur import apply_face_blur_ffmpeg

                    log("  [人脸] 开始人脸检测与模糊...")
                    blurred_output = output_folder / f"{main_video.stem}{suffix}_blurred.mp4"
                    ok = apply_face_blur_ffmpeg(
                        current_video,
                        blurred_output,
                        blur_strength=config.face_blur_strength,
                        blur_expand=config.face_blur_expand,
                        detect_every=config.face_detect_every,
                        log_callback=log,
                        cancel_check=cancel_check,
                    )
                    if ok and blurred_output.exists():
                        if current_video != compose_output:
                            try:
                                current_video.unlink()
                            except OSError:
                                pass
                        current_video = blurred_output
                        log(f"  [人脸] 模糊完成: {blurred_output.name}")
                    else:
                        failed_jobs += 1
                        elapsed_duration += main_dur
                        log("  [人脸] 模糊失败，本任务不生成伪成功成品")
                        compose_output.unlink(missing_ok=True)
                        blurred_output.unlink(missing_ok=True)
                        _report_progress(0.0)
                        continue

                # ── Pass 3: 字幕识别 + 烧录 ──
                if do_subtitle:
                    from engine.subtitle import (
                        SubtitleEngine,
                        extract_audio,
                        generate_srt,
                        generate_ass,
                        burn_subtitles,
                        get_style,
                    )

                    log("  [字幕] 开始语音识别...")
                    audio_file = extract_audio(
                        main_video,
                        output_dir=output_folder,
                        log_callback=log,
                    )
                    if not audio_file:
                        log("  [字幕] 音频提取失败，保留无字幕版本")
                        if current_video != output_path:
                            shutil.move(str(current_video), str(output_path))
                        current_video = output_path
                    else:
                        engine = SubtitleEngine(
                            model_size_or_path=config.subtitle_model,
                            log_callback=log,
                        )
                        segments, lang = engine.transcribe(audio_file)
                        segments = _wrap_subtitles(segments, config.subtitle_max_chars)
                        if not engine.is_available:
                            failed_jobs += 1
                            elapsed_duration += main_dur
                            log("  [字幕] 模型不可用，本任务失败")
                            audio_file.unlink(missing_ok=True)
                            current_video.unlink(missing_ok=True)
                            _report_progress(0.0)
                            continue

                        if not segments:
                            log("  [字幕] 未识别到语音，保留无字幕版本")
                            if current_video != output_path:
                                shutil.move(str(current_video), str(output_path))
                            current_video = output_path
                        else:
                            style = get_style(config.subtitle_style)
                            style.font_size = config.subtitle_font_size
                            w, h = map(int, config.resolution.split("x"))
                            style.margin_v = int(h * max(0, 100 - config.subtitle_pos_y) / 100)
                            ass_path = output_folder / f"{main_video.stem}{suffix}.ass"
                            generate_ass(segments, ass_path, style, w, h)

                            if config.subtitle_export_srt:
                                srt_path = output_folder / f"{main_video.stem}{suffix}.srt"
                                generate_srt(segments, srt_path)
                                log(f"  [字幕] SRT 已导出: {srt_path.name}")

                            log("  [字幕] 烧录字幕到视频...")
                            if burn_subtitles(current_video, ass_path, output_path, log_callback=log):
                                log(f"  [完成] {output_path.name} (含字幕)")
                                for tmp in [compose_output, current_video]:
                                    try:
                                        if tmp.exists() and tmp != output_path:
                                            tmp.unlink()
                                    except OSError:
                                        pass
                                try:
                                    ass_path.unlink()
                                except OSError:
                                    pass
                            else:
                                log("  [字幕] 烧录失败，保留无字幕版本")
                                shutil.move(str(current_video), str(output_path))

                        try:
                            if audio_file.exists():
                                audio_file.unlink()
                        except OSError:
                            pass

                elif do_face_blur and current_video != output_path:
                    shutil.move(str(current_video), str(output_path))
                    log(f"  [完成] {output_path.name} (人脸模糊)")

                elif not do_subtitle and not do_face_blur:
                    log(f"  [完成] {output_path.name}")

                # ── Pass 4: MP4 后处理 ──
                if config.mp4_enabled and output_path.exists():
                    from engine.mp4_tool import process_mp4
                    if config.mp4_hevc:
                        encoded = output_path.with_name(output_path.stem + "_hevc.mp4")
                        reencode = subprocess.run(
                            [
                                "ffmpeg", "-y", "-i", str(output_path),
                                "-c:v", "libx265", "-crf", str(config.crf),
                                "-preset", config.preset, "-c:a", "copy", str(encoded),
                            ],
                            capture_output=True, text=True,
                            **HIDDEN_SUBPROCESS,
                        )
                        if reencode.returncode == 0:
                            encoded.replace(output_path)
                        else:
                            log("  [MP4] H.265 二次编码失败，保留原编码")
                            encoded.unlink(missing_ok=True)
                    log("  [MP4] 元数据后处理...")
                    mp4_ok = process_mp4(
                        output_path,
                        track_id=(
                            None if config.mp4_id_follow
                            else config.mp4_track_id
                        ),
                        random_size=config.mp4_random_size,
                        layer_video=config.mp4_layer_video,
                        layer_audio=config.mp4_layer_audio,
                        elst_ms=config.mp4_elst_ms,
                        log_callback=log,
                    )
                    if not mp4_ok:
                        failed_jobs += 1
                        log("  [MP4] 后处理未生效，本任务标记失败")

                # 清理中间文件
                if needs_temp:
                    for tmp in [compose_output]:
                        try:
                            if tmp.exists() and tmp != output_path:
                                tmp.unlink()
                        except OSError:
                            pass

                # 模板模式下 background 就是模板文件，但模板是可复用的库而非
                # 一次性辅助素材 —— 「用完即删」在这里会删光用户的模板库，
                # 所以模板通道一律跳过该开关。
                if (
                    config.delete_used_aux
                    and template_window is None
                    and background is not None
                ):
                    try:
                        background.unlink()
                        backgrounds.remove(background)
                        log(f"    已删除辅助视频: {background.name}")
                    except OSError:
                        pass

            except FileNotFoundError:
                log("  [错误] 找不到 ffmpeg！请确保 ffmpeg 在系统 PATH 中")
                return False
            except Exception as e:
                failed_jobs += 1
                log(f"  [异常] {e}")

            # 本 job 完成，累计时长
            elapsed_duration += main_dur
            _report_progress(0.0)

    ok = failed_jobs == 0
    _elapsed = _time_module.time() - _start_time
    _elapsed_str = f"{int(_elapsed // 60)}分{int(_elapsed % 60)}秒" if _elapsed >= 60 else f"{_elapsed:.0f}秒"
    log(f"\n══════ 批量处理结束，成功 {total_jobs - failed_jobs}，失败 {failed_jobs}，耗时 {_elapsed_str} ══════")

    # 确保最终进度为 100%
    if progress_callback:
        progress_callback(int(total_duration * 1000), int(total_duration * 1000))

    return ok


def self_test(base_dir: Path, log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """环境自检：生成测试视频并完成一次完整合成。"""

    def log(msg: str) -> None:
        print(msg)
        if log_callback:
            log_callback(msg)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log("[失败] 找不到 ffmpeg，请将其添加到系统 PATH")
        return False
    log(f"[OK] ffmpeg: {ffmpeg}")

    log("正在生成测试素材...")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        main_dir = root / "main"
        bg_dir = root / "bg"
        out_dir = root / "output"
        main_dir.mkdir()
        bg_dir.mkdir()
        out_dir.mkdir()

        for name, source, folder in [
            ("main", "testsrc2=s=320x240:r=15:d=1", main_dir),
            ("bg", "smptebars=s=320x240:r=15:d=2", bg_dir),
        ]:
            r = subprocess.run(
                [
                    ffmpeg, "-y", "-f", "lavfi", "-i", source,
                    "-pix_fmt", "yuv420p", str(folder / f"{name}.mp4"),
                ],
                capture_output=True, text=True,
                **HIDDEN_SUBPROCESS,
            )
            if r.returncode != 0:
                log(f"[失败] 无法生成测试素材 {name}: {r.stderr[-200:]}")
                return False

        log("[OK] 测试素材生成成功")

        output = out_dir / "self-test.mp4"
        result = subprocess.run(
            [
                ffmpeg, "-y", "-i", str(bg_dir / "bg.mp4"),
                "-i", str(main_dir / "main.mp4"),
                "-filter_complex",
                "[0:v]scale=360:640[bg];[1:v]scale=320:240[main];"
                "[bg][main]overlay=(W-w)/2:(H-h)/2:shortest=1",
                "-an", "-c:v", "libx264", "-preset", "ultrafast",
                str(output),
            ],
            capture_output=True,
            text=True,
            **HIDDEN_SUBPROCESS,
        )
        if result.returncode != 0:
            log(f"[失败] 合成异常: {result.stderr[-200:]}")
            return False

        outputs = list(out_dir.glob("*.mp4"))
        if not outputs:
            log("[失败] 未生成输出文件")
            return False

        if outputs[0].stat().st_size < 1000:
            log("[失败] 输出文件过小")
            return False

        log(f"[OK] 自检通过！输出: {outputs[0].stat().st_size} bytes")
        return True
