"""素材拼接：头部、尾部可单选，也可同时拼接。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import AppConfig
from engine.concat import process_batch


def _video(path: Path, color: str, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color={color}:s=64x96:r=10:d={duration}",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _pixel(path: Path, at: float) -> tuple[int, int, int]:
    raw = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(at),
            "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return raw[0], raw[1], raw[2]


with TemporaryDirectory() as folder:
    root = Path(folder)
    mains = root / "mains"
    mains.mkdir()
    _video(mains / "甲.mp4", "blue", 0.4)
    _video(mains / "乙.mp4", "green", 0.4)
    head = root / "片头.mp4"
    tail = root / "片尾.mp4"
    _video(head, "red", 0.3)
    _video(tail, "yellow", 0.2)

    config = AppConfig(
        concat_main_folder=str(mains),
        concat_head_file=str(head),
        concat_tail_file=str(tail),
        concat_output_folder=str(root / "out"),
        concat_prepend=True,
        concat_append=False,
    )
    tasks = []
    assert process_batch(config, root, task_callback=tasks.append)
    outputs = sorted((root / "out").glob("*.mp4"))
    assert len(outputs) == 2 and len(tasks) == 2
    assert all(task["head"] == head and task["tail"] is None for task in tasks)
    blue_output = next(path for path in outputs if path.name.startswith("甲"))
    red, _, blue = _pixel(blue_output, 0.05)
    assert red > blue, (red, blue)  # 辅助素材在前

    config.concat_prepend = False
    config.concat_append = True
    assert process_batch(config, root)
    red, _, blue = _pixel(blue_output, 0.05)
    assert blue > red, (red, blue)  # 主素材在前

    config.concat_prepend = True
    tasks.clear()
    assert process_batch(config, root, task_callback=tasks.append)
    assert all(task["head"] == head and task["tail"] == tail for task in tasks)
    red, _, blue = _pixel(blue_output, 0.05)
    assert red > blue, (red, blue)
    red, green, blue = _pixel(blue_output, 0.8)
    assert red > blue and green > blue, (red, green, blue)  # 尾部黄色素材

    migrated = AppConfig.from_dict({
        "concat_aux_file": str(head), "concat_position": "前面",
    })
    assert migrated.concat_head_file == str(head)
    assert migrated.concat_prepend and not migrated.concat_append

print("concat test: OK (头部/尾部/头尾同时拼接通过)")
