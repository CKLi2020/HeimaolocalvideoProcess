"""批量素材拼接：可在每个主素材前、后分别拼接一个视频。"""

from __future__ import annotations

import json
import subprocess
import time
from fractions import Fraction
from pathlib import Path

from engine import HIDDEN_SUBPROCESS
from engine.ffmpeg_builder import VIDEO_EXTS, list_media
from engine.native_core import core as _native_core


def _media_info(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        **HIDDEN_SUBPROCESS,
    )
    data = json.loads(result.stdout)
    video = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "25/1"
    try:
        fps = float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        fps = 25.0
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "duration": max(duration, 0.01),
        "fps": max(1.0, fps),
        "audio": any(stream["codec_type"] == "audio" for stream in data["streams"]),
    }


def _filter_segment(index: int, info: dict, width: int, height: int, fps: float) -> list[str]:
    duration = info["duration"]
    return list(_native_core.concat_filter_segment(
        index, duration, info["audio"], width, height, fps,
    ))


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

    main_folder = resolve(config.concat_main_folder)
    output_folder = resolve(config.concat_output_folder)
    mains = list_media(str(main_folder), VIDEO_EXTS)
    if not mains:
        log("【错误】主素材文件夹里没有视频。")
        return False
    selected: list[tuple[str, Path]] = []
    if config.concat_prepend:
        selected.append(("头部", resolve(config.concat_head_file)))
    if config.concat_append:
        selected.append(("尾部", resolve(config.concat_tail_file)))
    if not selected:
        log("【错误】请至少选择一个拼接位置。")
        return False
    for position, path in selected:
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
            log(f"【错误】请选择有效的{position}素材文件。")
            return False

    output_folder.mkdir(parents=True, exist_ok=True)
    selected_info = [(position, path, _media_info(path)) for position, path in selected]
    total = len(mains)
    failed = 0
    log(f"主素材：{total} 个")
    for position, path, _ in selected_info:
        log(f"{position}素材：{path.name}")
    progress_callback and progress_callback(0, total)

    for number, main in enumerate(mains, 1):
        if cancel_check and cancel_check():
            return False
        task_callback and task_callback({
            "main": main,
            "head": resolve(config.concat_head_file) if config.concat_prepend else None,
            "tail": resolve(config.concat_tail_file) if config.concat_append else None,
            "positions": [f"拼到{position}" for position, _, _ in selected_info],
        })
        log(f"[{number}/{total}] 正在拼接：{main.name}")
        try:
            main_info = _media_info(main)
            width, height, fps = main_info["width"], main_info["height"], main_info["fps"]
            filters = _filter_segment(0, main_info, width, height, fps)
            inputs = [main]
            segment_indexes = [0]
            for position, path, info in selected_info:
                index = len(inputs)
                inputs.append(path)
                filters += _filter_segment(index, info, width, height, fps)
                if position == "头部":
                    segment_indexes.insert(0, index)
                else:
                    segment_indexes.append(index)
            streams = "".join(f"[v{index}][a{index}]" for index in segment_indexes)
            filters.append(
                f"{streams}concat=n={len(segment_indexes)}:v=1:a=1[v][a]"
            )
            output = output_folder / f"{main.stem}_拼接.mp4"
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                *[item for path in inputs for item in ("-i", str(path))],
                "-filter_complex", ";".join(filters),
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                str(output),
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
                    process.wait(timeout=5)
                    output.unlink(missing_ok=True)
                    return False
                time.sleep(0.2)
            error = process.communicate()[1]
            if process.returncode:
                failed += 1
                output.unlink(missing_ok=True)
                log(f"  【失败】{error.strip() or '未知错误'}")
            else:
                log(f"  【完成】{output.name}")
        except Exception as error:
            failed += 1
            log(f"  【失败】{error}")
        progress_callback and progress_callback(number, total)

    log(f"拼接结束：成功 {total - failed}，失败 {failed}。")
    return failed == 0
