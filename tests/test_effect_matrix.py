"""Verify that every visual control changes rendered pixels, not only the UI."""

from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import subprocess

from engine.pipeline import process_batch
from test_pipeline_smoke import _assets, _config


def _frame_digest(video: Path, second: float = 0.5) -> str:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(second), "-i", str(video),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True,
        check=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _render(root: Path, **changes) -> str:
    config = _config(root)
    for key, value in changes.items():
        setattr(config, key, value)
    assert process_batch(config, root)
    output = next((root / "out").glob("*.mp4"))
    digest = _frame_digest(output)
    output.unlink()
    return digest


def demo() -> None:
    cases = {
        "main_scale": dict(main_fit=False, main_scale=50),
        "aux_scale": dict(main_fit=False, main_scale=50, aux_scale=70),
        "mask": dict(mask_enabled=True, mask_margin_tb=10, mask_margin_lr=10),
        "top_matte": dict(top_step_enabled=True, top_opacity=50),
        "bars": dict(bars_enabled=True, top_bar_height=120, bottom_bar_height=100),
        "split_bars": dict(bars_enabled=True, split_bars_enabled=True),
        "line": dict(line_enabled=True),
        "pip1": dict(pip_enabled=True),
        "pip2": dict(pip2_enabled=True),
        "motion": dict(zoom_amp=5, sway_amp=3, shake_amp=2),
        "sticker": dict(sticker_enabled=True),
        "moving_sticker": dict(moving_sticker_enabled=True),
        "scanlight": dict(scanlight_enabled=True),
        "opening": dict(kaimu_enabled=True, kaimu_mode="素材-随机"),
        "cover": dict(cover_enabled=True, cover_follow_name=False, cover_text="TEST"),
        "brightness": dict(brightness=20),
        "contrast": dict(contrast=20),
        "saturation": dict(saturation=20),
        "temperature": dict(temperature=20),
        "vignette": dict(vignette=30),
        "preset_filter": dict(filter_name="黑白", filter_strength=100),
    }
    with TemporaryDirectory() as folder:
        root = Path(folder)
        _assets(root)
        baseline = _render(root)
        unchanged = [name for name, changes in cases.items()
                     if _render(root, **changes) == baseline]
        assert not unchanged, f"no visible effect: {unchanged}"


if __name__ == "__main__":
    demo()
    print("effect matrix: OK")
