"""本地多平台处理模式接入月落苍狼主窗口的冒烟测试。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

import engine.local_processor as local_engine

local_engine.detect_gpu_profile = lambda _path: {
    "available": False,
    "vendor": None,
    "vendor_label": "",
    "gpu_name": "NVIDIA GeForce RTX TEST",
    "warning": "",
}

from app.main_window import MainWindow
from config import AppConfig


app = QApplication.instance() or QApplication([])
window = MainWindow(AppConfig(), Path(__file__).resolve().parents[1])
page = window._local_processor_page

assert window._workspace_stack.count() == 4
assert window._active_channel == "local_processor"
assert window._workspace_stack.currentWidget() is page
assert "NVIDIA GeForce RTX TEST" in window._machine_gpu.text()
assert "不支持 GPU 加速" in window._machine_gpu.text()
assert [button.text() for button in window._channel_group.buttons()][:3] == [
    "视频处理", "蒙版模式", "素材拼接",
]
assert len(page.service.mode_groups) == 8
assert page.current_mode is not None
assert page.start_button.text() == "▶ 开始处理"

window.close()
print("local processor integration: OK (8 platforms)")
