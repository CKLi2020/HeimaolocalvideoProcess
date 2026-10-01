"""Small end-to-end checks for the shared FFmpeg composition chain."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess

from config import AppConfig
from engine.ffmpeg_builder import build_ffmpeg_command
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
    # 比主视频短，验证辅助叠层会循环到主视频结束。
    _ffmpeg("-f", "lavfi", "-i", "color=blue:s=320x240:r=15:d=0.25",
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
        tpl_enabled=False,
        # 基线显式关掉移动贴纸，保证后面每项检查只开一个效果。
        moving_sticker_enabled=False,
        kaimu_enabled=False,
        playback_speed_min=1.0,
        playback_speed_max=1.0,
        filter_name="无",
        filter_segment_count=1,
        scanlight_enabled=False,
        aux_overlay_count=3,
        aux_opacity_min=2,
        aux_opacity_max=2,
        aux_layers_json=json.dumps([
            {"file": "", "opacity_min": 1, "opacity_max": 1},
            {"file": "", "opacity_min": 2, "opacity_max": 2},
            {"file": "", "opacity_min": 3, "opacity_max": 3},
        ]),
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
            assert tasks[0]["background"] is None
            assert len(tasks[0]["auxiliary_videos"]) == 3
            assert {path.name for path in tasks[0]["auxiliary_videos"]} == {"bg.mp4"}
            assert tasks[0]["auxiliary_opacities"] == [0.02, 0.02, 0.02]
            outputs = list((root / "out").glob("*.mp4"))
            assert outputs and outputs[0].stat().st_size > 1000, options
            duration = float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(outputs[0])],
                capture_output=True, text=True, check=True,
            ).stdout)
            assert duration >= 0.9, duration
            for output in outputs:
                output.unlink()

        # 辅助素材不再逐层指定，全部从文件夹随机选择。
        _ffmpeg("-f", "lavfi", "-i", "color=red:s=320x240:r=15:d=2",
                "-pix_fmt", "yuv420p", str(root / "bg" / "fixed.mp4"))
        config = _config(root)
        tasks = []
        assert process_batch(config, root, task_callback=tasks.append)
        assert tasks[0]["background"] is None
        assert len(tasks[0]["auxiliary_videos"]) == 3
        assert {path.name for path in tasks[0]["auxiliary_videos"]} == {
            "bg.mp4", "fixed.mp4",
        }
        for output in (root / "out").glob("*.mp4"):
            output.unlink()

        # 按数量等分时长，每段使用一个随机滤镜。
        config = _config(root)
        config.filter_segment_count = 3
        tasks = []
        assert process_batch(config, root, task_callback=tasks.append)
        segments = tasks[0]["filter_segments"]
        assert len(segments) == 3
        assert all(left != right for left, right in zip(segments, segments[1:]))
        assert next((root / "out").glob("*.mp4")).stat().st_size > 1000
        for output in (root / "out").glob("*.mp4"):
            output.unlink()

        # 辅助模式的 input 0 是黑色画布；横条必须改从主视频 input 1 取样。
        config = _config(root)
        config.bars_enabled = True
        command = build_ffmpeg_command(
            config, root / "main" / "main.mp4", None,
            root / "out" / "bars-source-check.mp4",
        )
        filter_complex = command[command.index("-filter_complex") + 1]
        assert "[1:v]scale=360:640:force_original_aspect_ratio=increase" in filter_complex

        # 透明度为 0 时保持主视频原比例，画布多出的上下区域直接填黑。
        config.bars_enabled = False
        config.top_step_enabled = False
        config.aux_opacity_min = config.aux_opacity_max = 0
        assert process_batch(config, root)
        output = next((root / "out").glob("*.mp4"))
        top_band = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.1",
             "-i", str(output), "-vf", "crop=iw:ih/4:0:0,format=gray",
             "-frames:v", "1", "-f", "rawvideo", "-"],
            capture_output=True, check=True,
        ).stdout
        assert top_band and sum(top_band) / len(top_band) < 5
        output.unlink()

        # 只在成片成功后删除实际使用过的辅助视频；重复选中也只删一次。
        config.delete_used_aux = True
        assert (root / "bg" / "fixed.mp4").exists()
        assert process_batch(config, root)
        assert not (root / "bg" / "fixed.mp4").exists()
        assert not (root / "bg" / "bg.mp4").exists()


if __name__ == "__main__":
    demo()
    print("pipeline smoke test: OK")
