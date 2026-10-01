"""长视频快速切片：按关键帧分段，流复制、不损画质。"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

from engine import HIDDEN_SUBPROCESS
from engine.ffmpeg_builder import VIDEO_EXTS, list_media


def process_batch(
    config,
    base_dir: Path,
    log_callback=None,
    progress_callback=None,
    cancel_check=None,
    task_callback=None,
) -> bool:
    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else base_dir / path

    def log(message: str) -> None:
        if log_callback:
            log_callback(message)

    main_folder = resolve(config.cut_main_folder)
    output_folder = resolve(config.cut_output_folder)
    videos = list_media(str(main_folder), VIDEO_EXTS)
    if not videos:
        log("【错误】长视频文件夹里没有视频。")
        return False

    seconds = max(1, int(config.cut_segment_seconds))
    output_folder.mkdir(parents=True, exist_ok=True)
    total, failed = len(videos), 0
    progress_callback and progress_callback(0, total)
    log(f"待裁剪视频：{total} 个；每段目标时长：{seconds} 秒")

    for number, video in enumerate(videos, 1):
        if cancel_check and cancel_check():
            return False
        task_callback and task_callback({"main": video})
        token = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        pattern = output_folder / f"{video.stem}_{token}_片段_%04d{video.suffix.lower()}"
        log(f"[{number}/{total}] 正在裁剪：{video.name}")
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video), "-map", "0:v:0", "-map", "0:a?",
            "-c", "copy", "-f", "segment", "-segment_time", str(seconds),
            "-reset_timestamps", "1", "-segment_start_number", "1", str(pattern),
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **HIDDEN_SUBPROCESS,
        )
        while process.poll() is None:
            if cancel_check and cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                log("【取消】已停止当前视频裁剪，已完成的小片段予以保留。")
                return False
            time.sleep(0.2)
        error = process.communicate()[1]
        clips = sorted(output_folder.glob(f"{video.stem}_{token}_片段_*{video.suffix.lower()}"))
        if process.returncode or not clips:
            failed += 1
            log(f"  【失败】{error.strip() or '没有生成切片'}")
        else:
            log(f"  【完成】生成 {len(clips)} 个小视频")
        progress_callback and progress_callback(number, total)

    log(f"裁剪结束：成功 {total - failed}，失败 {failed}。")
    return failed == 0
