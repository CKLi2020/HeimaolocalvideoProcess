"""Small end-to-end checks for the shared FFmpeg composition chain."""

from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess

from config import AppConfig
from engine.pipeline import process_batch


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
    )


def _assets(root: Path) -> None:
    for name in ("main", "bg", "sticker", "scan", "open", "out"):
        (root / name).mkdir()
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=15:d=1",
            "-pix_fmt", "yuv420p", str(root / "main" / "main.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "color=blue:s=320x240:r=15:d=2",
            "-pix_fmt", "yuv420p", str(root / "bg" / "bg.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "color=white@0.5:s=80x80:d=1",
            "-frames:v", "1", str(root / "sticker" / "sticker.png"))
    _ffmpeg("-f", "lavfi", "-i", "color=white:s=320x240:r=15:d=2",
            "-pix_fmt", "yuv420p", str(root / "scan" / "scan.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "color=red:s=320x240:d=1",
            "-frames:v", "1", str(root / "open" / "open.png"))


def _config(root: Path) -> AppConfig:
    return AppConfig(
        main_folder=str(root / "main"),
        background_folder=str(root / "bg"),
        sticker_folder=str(root / "sticker"),
        moving_sticker_folder=str(root / "sticker"),
        scanlight_folder=str(root / "scan"),
        kaimu_folder=str(root / "open"),
        output_folder=str(root / "out"),
        resolution="360x640",
        fps=15,
        main_scale=90,
        mask_enabled=False,
        sticker_enabled=False,
        # 显式关掉移动贴纸。默认是 True，不写的话基线里本来就有移动贴纸，
        # test_effect_matrix 的「打开移动贴纸」用例就成了空操作（基线已是开的），
        # 于是断言「画面有可见变化」必然失败——它不是产品 bug，是基线没配干净。
        moving_sticker_enabled=False,
        scanlight_enabled=False,
    )


def demo() -> None:
    cases = (
        {},
        dict(mask_enabled=True, bars_enabled=True, split_bars_enabled=True,
             line_enabled=True, top_step_enabled=True),
        dict(pip_enabled=True, pip_move=True, pip2_enabled=True, pip2_move=True,
             zoom_amp=2, sway_amp=2, shake_amp=2),
        dict(sticker_enabled=True, moving_sticker_enabled=True,
             scanlight_enabled=True, kaimu_enabled=True, cover_enabled=True,
             brightness=10, contrast=10, saturation=10, temperature=10,
             vignette=10),
    )
    with TemporaryDirectory() as folder:
        root = Path(folder)
        _assets(root)
        for options in cases:
            config = _config(root)
            for key, value in options.items():
                setattr(config, key, value)
            tasks = []
            assert process_batch(config, root, task_callback=tasks.append), options
            assert len(tasks) == 1
            assert tasks[0]["main"].name == "main.mp4"
            assert tasks[0]["background"].name == "bg.mp4"
            outputs = list((root / "out").glob("*.mp4"))
            assert outputs and outputs[0].stat().st_size > 1000, options
            for output in outputs:
                output.unlink()


if __name__ == "__main__":
    demo()
    print("pipeline smoke test: OK")
