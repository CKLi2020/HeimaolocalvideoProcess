"""视频裁剪通道回归。可直接运行。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from config import AppConfig
from engine.cut import process_batch

app = QApplication.instance() or QApplication([])

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    source = root / "长视频"
    output = root / "裁剪成品"
    source.mkdir()
    video = source / "一小时示例.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=64x96:r=10:d=8",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-c:v", "libx264", "-g", "10", "-keyint_min", "10",
        "-sc_threshold", "0", "-c:a", "aac", "-shortest", str(video),
    ], check=True, capture_output=True)

    config = AppConfig(
        cut_main_folder=str(source),
        cut_output_folder=str(output),
        cut_segment_seconds=3,
    )
    logs: list[str] = []
    assert process_batch(config, root, logs.append)
    clips = sorted(output.glob("*.mp4"))
    assert len(clips) == 3, clips
    durations = []
    for clip in clips:
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_format", "-of", "json", str(clip),
        ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        durations.append(float(json.loads(probe.stdout)["format"]["duration"]))
    assert all(1.5 <= value <= 3.5 for value in durations), durations
    assert any("生成 3 个" in line for line in logs)

    window = MainWindow(config, root)
    window.show()
    app.processEvents()
    cut_buttons = [
        button for button in window._channel_group.buttons()
        if "视频裁剪" in button.text()
    ]
    assert len(cut_buttons) == 1 and cut_buttons[0].isHidden()
    window._select_channel("cut")
    assert window._workspace_stack.currentWidget() is window._cut_page
    assert hasattr(window._pages["声音处理"], "_speed_row")
    assert "audio_voice_mild" in window._pages["声音处理"]._rows
    assert "aux_overlay_count" in window._pages["模板"]._rows
    assert "aux_opacity_range" in window._pages["模板"]._rows
    assert "filter_segment_count" in window._pages["画面滤镜"]._rows
    window.close()

print("cut test: OK (8 秒视频按 3 秒拆成 3 段)")
