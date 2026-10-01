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

assert window._workspace_stack.count() == 5
assert window._active_channel == "local_processor"
assert window._workspace_stack.currentWidget() is page
assert "NVIDIA GeForce RTX TEST" in window._machine_gpu.text()
assert "不支持 GPU 加速" in window._machine_gpu.text()
assert [button.text() for button in window._channel_group.buttons()][:4] == [
    "视频处理", "蒙版模式", "素材拼接", "视频裁剪",
]
channel_buttons = {button.text(): button for button in window._channel_group.buttons()}
assert channel_buttons["素材拼接"].isHidden()
assert channel_buttons["视频裁剪"].isHidden()
assert len(page.service.mode_groups) == 8
assert page.current_mode is not None
assert page.start_button.text() == "▶ 开始处理"
assert all(not page._platforms[title][1].isEnabled() for title in (
    "TK处理", "百家处理", "哔哩处理", "多多处理",
))
assert all(page._platforms[title][1].isEnabled() for title in (
    "抖音处理", "快手处理", "视频号处理", "小红书处理",
))

_frame, shipinhao = page._platforms["视频号处理"]
assert shipinhao.currentText() == "爆闪"
heimao_index = next(
    index for index in range(shipinhao.count())
    if shipinhao.itemData(index).id == "shipinhao/heimao_luoyue"
)
shipinhao.setCurrentIndex(heimao_index)
page._activate("视频号处理")
assert not page.aux_edit.isEnabled()
assert page.aux_edit.text() == "本通道不需要辅助视频"
assert all(not button.isEnabled() for button in page.aux_edit._path_buttons)

needs_aux_index = next(
    index for index in range(shipinhao.count())
    if shipinhao.itemData(index).needs_aux
)
shipinhao.setCurrentIndex(needs_aux_index)
page._activate("视频号处理")
assert page.aux_edit.isEnabled() and not page.aux_edit.text()
assert all(button.isEnabled() for button in page.aux_edit._path_buttons)

window.close()
print("local processor integration: OK (8 platforms)")
