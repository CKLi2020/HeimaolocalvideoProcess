"""批量处理管道：遍历主素材，随机选择背景/贴纸/扫光，调用 ffmpeg 合成。
Phase 2: 集成字幕识别和烧录（两遍编码）。
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Callable, Optional

from config import AppConfig
from engine.ffmpeg_builder import (
    VIDEO_EXTS,
    IMAGE_EXTS,
    list_media,
    pick_random,
    build_ffmpeg_command,
)
from engine.output_naming import output_name


def _wrap_subtitles(segments: list[dict], max_chars: int) -> list[dict]:
    """Wrap recognized text without changing timestamps."""
    width = max(1, max_chars)
    return [
        {**segment, "text": "\n".join(textwrap.wrap(segment["text"], width=width))}
        for segment in segments
    ]


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
        base_dir: 程序根目录（用于相对路径解析）
        log_callback: 日志回调
        progress_callback: 进度回调 (current, total)
        cancel_check: 返回 True 表示用户请求取消
    """

    def log(msg: str) -> None:
        print(msg)
        if log_callback:
            log_callback(msg)

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else base_dir / path

    def run_ffmpeg(command: list[str]) -> Optional[subprocess.CompletedProcess]:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        while process.poll() is None:
            if cancel_check and cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                log("[取消] 已终止当前 FFmpeg")
                return None
            try:
                process.communicate(timeout=0.2)
            except subprocess.TimeoutExpired:
                continue
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(
            command, process.returncode, stdout, stderr
        )

    # 解析所有路径
    main_folder = resolve(config.main_folder)
    background_folder = resolve(config.background_folder)
    output_folder = resolve(config.output_folder)
    sticker_folder = resolve(config.sticker_folder)
    moving_sticker_folder = resolve(
        config.moving_sticker_folder or config.sticker_folder
    )
    scanlight_folder = resolve(config.scanlight_folder)
    kaimu_folder = resolve(config.kaimu_folder)

    output_folder.mkdir(parents=True, exist_ok=True)

    # 列出素材
    mains = list_media(str(main_folder), VIDEO_EXTS)
    backgrounds = list_media(str(background_folder), VIDEO_EXTS)

    if not mains:
        log("[错误] 主素材文件夹中没有视频文件")
        return False
    if not backgrounds:
        log("[错误] 背景视频文件夹中没有视频文件")
        return False

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

    total_jobs = len(mains) * config.repeat_count
    current_job = 0
    failed_jobs = 0

    for main_video in mains:
        if cancel_check and cancel_check():
            log("[取消] 用户停止了处理")
            return False

        log(f"\n━━━ 处理: {main_video.name} ━━━")

        for repeat in range(config.repeat_count):
            if cancel_check and cancel_check():
                log("[取消] 用户停止了处理")
                return False

            current_job += 1
            if progress_callback:
                progress_callback(current_job, total_jobs)

            # 随机选择素材
            backgrounds = [path for path in backgrounds if path.exists()]
            if not backgrounds:
                log("  [错误] 可用辅助视频已耗尽")
                failed_jobs += total_jobs - current_job + 1
                return False
            background = random.choice(backgrounds)

            sticker_files = []
            if config.sticker_enabled:
                sfiles = list_media(str(sticker_folder), VIDEO_EXTS | IMAGE_EXTS)
                # 从 sticker_layers_json 读取层数，否则默认 1 层
                import json as _json
                try:
                    layers = _json.loads(config.sticker_layers_json) if config.sticker_layers_json else []
                except Exception:
                    layers = []
                num_layers = len(layers) if layers else 1
                # ponytail: two alternating groups keep FFmpeg inputs bounded.
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

            mover_files = []
            if config.moving_sticker_enabled:
                mfiles = list_media(
                    str(moving_sticker_folder), VIDEO_EXTS | IMAGE_EXTS
                )
                import json as _json
                try:
                    mlayers = _json.loads(config.mover_layers_json) if config.mover_layers_json else []
                except Exception:
                    mlayers = []
                num_movers = len(mlayers) if mlayers else 1
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
                })

            # 输出文件名
            suffix = f"_{repeat + 1}" if config.repeat_count > 1 else ""
            output_path = output_folder / output_name(main_video)

            # 多阶段后处理管线：
            #   Pass 1: ffmpeg 合成 → compose_output
            #   Pass 2: [可选] 人脸模糊 → blurred_output
            #   Pass 3: [可选] 字幕识别 + 烧录 → output_path
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

            # ── Pass 1: 视频合成 ──
            cmd = build_ffmpeg_command(
                config,
                main_video=main_video,
                background_video=background,
                output_path=compose_output,
                sticker_files=sticker_files or None,
                scanlight_file=scanlight_file,
                kaimu_file=kaimu_file,
                mover_files=mover_files or None,
            )

            log(f"  [{current_job}/{total_jobs}] {main_video.stem}{suffix}")
            log(f"    背景: {background.name}")
            if sticker_files:
                log(f"    贴纸: {len(sticker_files)} 层")
            if scanlight_file:
                log(f"    扫光: {scanlight_file.name}")

            try:
                result = run_ffmpeg(cmd)
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
                    result = run_ffmpeg(cpu_cmd)
                    if result is None:
                        compose_output.unlink(missing_ok=True)
                        return False
                if result.returncode != 0:
                    failed_jobs += 1
                    log(f"  [失败] ffmpeg 返回码 {result.returncode}")
                    stderr_lines = result.stderr.strip().split("\n")
                    for line in stderr_lines[-15:]:
                        if line.strip():
                            log(f"    {line.strip()}")
                    continue  # 跳过字幕处理，继续下一个

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
                        # 清理上一个中间文件
                        if current_video != compose_output:
                            try:
                                current_video.unlink()
                            except OSError:
                                pass
                        current_video = blurred_output
                        log(f"  [人脸] 模糊完成: {blurred_output.name}")
                    else:
                        failed_jobs += 1
                        log("  [人脸] 模糊失败，本任务不生成伪成功成品")
                        compose_output.unlink(missing_ok=True)
                        blurred_output.unlink(missing_ok=True)
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

                    # 提取音频
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
                        # 语音识别
                        engine = SubtitleEngine(
                            model_size_or_path=config.subtitle_model,
                            log_callback=log,
                        )
                        segments, lang = engine.transcribe(audio_file)
                        segments = _wrap_subtitles(segments, config.subtitle_max_chars)
                        if not engine.is_available:
                            failed_jobs += 1
                            log("  [字幕] 模型不可用，本任务失败")
                            audio_file.unlink(missing_ok=True)
                            current_video.unlink(missing_ok=True)
                            continue

                        if not segments:
                            log("  [字幕] 未识别到语音，保留无字幕版本")
                            if current_video != output_path:
                                shutil.move(str(current_video), str(output_path))
                            current_video = output_path
                        else:
                            # 生成 ASS 字幕（比 SRT 样式好）
                            style = get_style(config.subtitle_style)
                            style.font_size = config.subtitle_font_size
                            style.margin_v = int(
                                h * max(0, 100 - config.subtitle_pos_y) / 100
                            )
                            w, h = map(int, config.resolution.split("x"))
                            ass_path = output_folder / f"{main_video.stem}{suffix}.ass"
                            generate_ass(segments, ass_path, style, w, h)

                            # 导出 SRT（如果用户勾选）
                            if config.subtitle_export_srt:
                                srt_path = output_folder / f"{main_video.stem}{suffix}.srt"
                                generate_srt(segments, srt_path)
                                log(f"  [字幕] SRT 已导出: {srt_path.name}")

                            # 烧录字幕到视频
                            log("  [字幕] 烧录字幕到视频...")
                            if burn_subtitles(current_video, ass_path, output_path, log_callback=log):
                                log(f"  [完成] {output_path.name} (含字幕)")
                                # 清理中间文件
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

                        # 清理音频临时文件
                        try:
                            if audio_file.exists():
                                audio_file.unlink()
                        except OSError:
                            pass

                elif do_face_blur and current_video != output_path:
                    # 只有人脸模糊、无字幕：将模糊后的视频移到最终输出
                    shutil.move(str(current_video), str(output_path))
                    log(f"  [完成] {output_path.name} (人脸模糊)")

                elif not do_subtitle and not do_face_blur:
                    log(f"  [完成] {output_path.name}")

                # ── Pass 4: MP4 后处理 (元数据编辑) ──
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

                # ── 清理中间文件 ──
                if needs_temp:
                    for tmp in [compose_output]:
                        try:
                            if tmp.exists() and tmp != output_path:
                                tmp.unlink()
                        except OSError:
                            pass

                # ── 可选：删除已用辅助视频 ──
                if config.delete_used_aux:
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

    ok = failed_jobs == 0
    log(f"\n══════ 批量处理结束，成功 {total_jobs - failed_jobs}，失败 {failed_jobs} ══════")
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

        # 生成测试视频 (1 秒)
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
            )
            if r.returncode != 0:
                log(f"[失败] 无法生成测试素材 {name}: {r.stderr[-200:]}")
                return False

        log("[OK] 测试素材生成成功")

        # 用最小配置运行合成
        test_config = AppConfig()
        test_config.main_folder = str(main_dir)
        test_config.background_folder = str(bg_dir)
        test_config.output_folder = str(out_dir)
        test_config.sticker_enabled = False
        test_config.scanlight_enabled = False
        test_config.kaimu_enabled = False
        test_config.moving_sticker_enabled = False
        test_config.gpu = False
        test_config.repeat_count = 1
        test_config.mask_enabled = False
        test_config.bars_enabled = False

        try:
            process_batch(test_config, base_dir, log_callback=log_callback)
        except Exception as e:
            log(f"[失败] 合成异常: {e}")
            return False

        # 检查输出
        outputs = list(out_dir.glob("*.mp4"))
        if not outputs:
            log("[失败] 未生成输出文件")
            return False

        if outputs[0].stat().st_size < 1000:
            log("[失败] 输出文件过小")
            return False

        log(f"[OK] 自检通过！输出: {outputs[0].stat().st_size} bytes")
        return True
