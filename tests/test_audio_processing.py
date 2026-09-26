"""声音处理页与 FFmpeg 音轨链回归。可直接运行。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from app.pages.audio_page import AudioPage
from config import AppConfig
from engine.ffmpeg_builder import build_ffmpeg_command
from engine.pipeline import _adaptive_voice_shift, _estimate_voice_pitch


app = QApplication.instance() or QApplication([])

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    music = root / "音乐"
    music.mkdir()
    fixed = music / "固定.mp3"
    fixed.write_bytes(b"test")

    config = AppConfig(
        audio_bgm_enabled=True,
        audio_bgm_folder=str(music),
        audio_bgm_pick="固定",
        audio_bgm_fixed=fixed.name,
        audio_bgm_volume=15,
        audio_voice_enabled=True,
        audio_voice_pitch=2,
    )
    page = AudioPage(config, root)
    assert page._fixed_row.available == [fixed.name]
    assert page._fixed_row.isEnabled()
    assert "整批" in page._fixed_hint.text()

    cmd = build_ffmpeg_command(
        config, root / "main.mp4", None, root / "out.mp4",
        background_audio=fixed, main_has_audio=True,
    )
    filters = cmd[cmd.index("-filter_complex") + 1]
    assert "rubberband=pitch=" in filters
    assert "formant=shifted:pitchq=quality" in filters
    assert "volume=0.150[bgm]" in filters
    assert "amix=inputs=2:duration=first" in filters
    assert "[mixed_audio]" in cmd

    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        main = root / "main_real.mp4"
        bgm = root / "bgm.wav"
        out = root / "out_real.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=64x96:r=10:d=1",
            "-f", "lavfi", "-i", "sine=frequency=110:duration=1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(main),
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
            str(bgm),
        ], check=True, capture_output=True)
        config.resolution = "64x96"
        config.fps = 10
        config.gpu = False
        config.preset = "ultrafast"
        config.sticker_enabled = False
        config.moving_sticker_enabled = False
        real_cmd = build_ffmpeg_command(
            config, main, None, out, background_audio=bgm, main_has_audio=True,
        )
        subprocess.run(real_cmd, check=True, capture_output=True)
        detected = _estimate_voice_pitch(main)
        assert detected is not None and 100 <= detected <= 120, detected
        assert _adaptive_voice_shift(110) == 2.0
        assert _adaptive_voice_shift(220) == -2.0
        assert _adaptive_voice_shift(None) == 0.0

print("audio processing test: OK")
