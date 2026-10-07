"""本地多平台处理模式接入月落苍狼主窗口的冒烟测试。"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QFrame

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
import modes


source_modes_dir = modes.MODES_DIR
modes.MODES_DIR = str(Path(__file__).resolve().parent / "missing-packaged-modes")
try:
    packaged_groups = modes.load_modes()
finally:
    modes.MODES_DIR = source_modes_dir
assert list(packaged_groups) == [
    "抖音处理", "快手处理", "视频号处理", "小红书处理",
    "TK处理", "百家处理", "哔哩处理", "千川处理",
]
assert [mode.name for mode in packaged_groups["千川处理"]] == ["刹夜黑五", "漫落惊鸿"]
assert [mode.name for mode in packaged_groups["视频号处理"]] == [
    "立梦1007", "流萤1003", "栖霞", "爆闪", "云水", "青岚",
]


app = QApplication.instance() or QApplication([])
window = MainWindow(AppConfig(), Path(__file__).resolve().parents[1])
page = window._local_processor_page
assert window.findChild(QFrame, "channelBar").minimumWidth() == 230

assert window._workspace_stack.count() == 5
assert window._active_channel == "local_processor"
assert window._workspace_stack.currentWidget() is page
assert "NVIDIA GeForce RTX TEST" in window._machine_gpu.text()
assert "不支持 GPU 加速" in window._machine_gpu.text()
assert [button.text() for button in window._channel_group.buttons()][:4] == [
    "科技板块", "蒙版板块", "素材拼接", "视频裁剪",
]
channel_buttons = {button.text(): button for button in window._channel_group.buttons()}
assert channel_buttons["素材拼接"].isHidden()
assert channel_buttons["视频裁剪"].isHidden()
assert len(page.service.mode_groups) == 8
assert page.current_mode is not None
assert page.start_button.text() == "▶ 开始处理"
assert all(not page._platforms[title][1].isEnabled() for title in (
    "TK处理", "百家处理", "哔哩处理",
))
assert all(page._platforms[title][1].isEnabled() for title in (
    "抖音处理", "快手处理", "视频号处理", "小红书处理", "千川处理",
))

_frame, qianchuan = page._platforms["千川处理"]
assert [qianchuan.itemText(i) for i in range(qianchuan.count())] == ["刹夜黑五", "漫落惊鸿"]
page._activate("千川处理")
assert page.current_mode.id == "duoduo/shaye_heiw"
assert not page.shaye_options.isHidden()
assert not page.shaye_settings_button.isHidden()
page.shaye_settings_button.click()
assert page.shaye_dialog.isVisible()
assert page.shaye_dialog.windowTitle() == "刹夜黑五参数设置"
page.shaye_dialog.accept()
assert not page.shaye_dialog.isVisible()
assert page.tianqiong_options.isHidden()
assert not page.copies_spin.isHidden()
assert page.shaye_audio_enabled.isChecked()
assert page.shaye_audio_mode.currentText() == "汉语方言"
assert page.shaye_face_enabled.isChecked()
assert not page.shaye_cover_row.isHidden()
page.main_edit.setText("main.mp4")
with patch.object(page, "_files", return_value=[Path("main.mp4")]):
    with patch.object(page.service, "start", return_value=True) as shaye_start:
        page.start()
shaye_state = shaye_start.call_args.args[0]
assert shaye_state["shaye_audio_enabled"]
assert shaye_state["shaye_audio_mode"] == "汉语方言"
assert shaye_state["shaye_face_enabled"]
assert shaye_state["shaye_cover"] == ""
assert shaye_start.call_args.args[1].id == "duoduo/shaye_heiw"
page._on_done(0, 0, 0, "", False)

manluo_index = next(
    index for index in range(qianchuan.count())
    if qianchuan.itemData(index).id == "duoduo/manluo_jinghong"
)
qianchuan.setCurrentIndex(manluo_index)
page._activate("千川处理")
assert page.current_mode.id == "duoduo/manluo_jinghong"
assert not page.tianqiong_options.isHidden()
assert page.shaye_options.isHidden()
assert page.shaye_cover_row.isHidden()
assert page.dedup_mode.currentText() == "中度"

_frame, shipinhao = page._platforms["视频号处理"]
assert [shipinhao.itemText(i) for i in range(shipinhao.count())] == [
    "立梦1007", "流萤1003", "栖霞", "爆闪", "云水", "青岚",
]
assert shipinhao.currentText() == "立梦1007"
liuying_index = next(
    index for index in range(shipinhao.count())
    if shipinhao.itemData(index).id == "shipinhao/liuying_v15"
)
shipinhao.setCurrentIndex(liuying_index)
page._activate("视频号处理")
assert page.current_mode.id == "shipinhao/liuying_v15"
assert not hasattr(page, "random_enhance")
assert not page.copies_spin.isHidden()
assert not page.copies_label.isHidden()
assert page.copies_spin.value() == 1
assert page.copies_spin.minimum() == 1 and page.copies_spin.maximum() == 100
assert not page.aux_edit.isEnabled()
assert page.aux_edit.text() == "本通道不需要辅助视频"
assert all(not button.isEnabled() for button in page.aux_edit._path_buttons)
assert not page.current_mode.needs_aux
page.copies_spin.setValue(3)
assert page.current_mode.output_count({"copies": page.copies_spin.value()}) == 3
page.main_edit.setText("main.mp4")
with patch.object(page, "_files", return_value=[Path("main.mp4")]) as files:
    with patch.object(page.service, "start", return_value=True) as start:
        page.start()
assert start.call_count == 1
submitted = start.call_args.args
assert submitted[0]["copies"] == 3
assert "random_enhance" not in submitted[0]
assert submitted[1].id == "shipinhao/liuying_v15"
assert submitted[2:4] == ([Path("main.mp4")], [])
assert files.call_count == 1
page._on_done(0, 0, 0, "", False)
page.copies_spin.setValue(1)
heimao_index = next(
    index for index in range(shipinhao.count())
    if shipinhao.itemData(index).id == "shipinhao/heimao_luoyue"
)
shipinhao.setCurrentIndex(heimao_index)
page._activate("视频号处理")
assert "#60a5fa" in page._platforms["视频号处理"][0].styleSheet()
assert "#2c456d" in page._platforms["抖音处理"][0].styleSheet()
assert not page.aux_edit.isEnabled()
assert page.aux_edit.text() == "本通道不需要辅助视频"
assert all(not button.isEnabled() for button in page.aux_edit._path_buttons)
assert page.mode5_options.isHidden()

qixia_index = next(
    index for index in range(shipinhao.count())
    if shipinhao.itemData(index).id == "shipinhao/qixia_mode5"
)
assert qixia_index == 2
shipinhao.setCurrentIndex(qixia_index)
page._activate("视频号处理")
assert page.current_mode.name == "栖霞"
assert not page.aux_edit.isEnabled()
assert all(not button.isEnabled() for button in page.aux_edit._path_buttons)
assert not page.mode5_options.isHidden()
assert not page.copies_spin.isHidden()
assert page.copies_label.text() == "裂变个数："
assert page.copies_spin.value() == 1
assert page.mode5_ronghe.isChecked()
assert not page.mode5_lasong.isChecked() and not page.mode5_daoli.isChecked()
assert page.mode5_lasong.text() == "拉伸"
assert page.mode5_opacity.value() == 50
assert page.mode5_opacity.minimum() == 0 and page.mode5_opacity.maximum() == 100
assert page.output_edit.text() == str(page.root_dir / "capture")
assert page.output_edit.isReadOnly()
assert all(not button.isEnabled() for button in page.output_edit._path_buttons)

limeng_index = next(
    index for index in range(shipinhao.count())
    if shipinhao.itemData(index).id == "shipinhao/limeng_1007"
)
assert limeng_index == 0
shipinhao.setCurrentIndex(limeng_index)
page._activate("视频号处理")
assert page.current_mode.name == "立梦1007"
assert page.mode5_options.isHidden()
assert not page.aux_edit.isEnabled()
assert not page.output_edit.isReadOnly()
assert page.output_edit.text() == str(page.root_dir / "output")
assert all(button.isEnabled() for button in page.output_edit._path_buttons)
selected_output = str(page.root_dir / "output" / "user-selected-qixia")
with patch("app.pages.local_processor_page.QFileDialog.getExistingDirectory",
           return_value=selected_output):
    page.output_edit._path_buttons[0].click()
assert page.output_edit.text() == selected_output
page.main_edit.setText("main.mp4")
with patch.object(page, "_files", return_value=[Path("main.mp4")]):
    with patch.object(page.service, "start", return_value=True) as limeng_start:
        page.start()
assert limeng_start.call_args.args[0]["output_dir"] == selected_output
assert limeng_start.call_args.args[0]["tool_root"] == str(page.root_dir.resolve())
assert limeng_start.call_args.args[1].id == "shipinhao/limeng_1007"
assert limeng_start.call_args.args[3] == []
page._on_done(0, 0, 0, "", False)

shipinhao.setCurrentIndex(heimao_index)
page._activate("视频号处理")
assert page.mode5_options.isHidden()
assert not page.output_edit.isReadOnly()
assert page.output_edit.text() == selected_output

caishen_index = next(
    index for index in range(shipinhao.count())
    if shipinhao.itemData(index).id == "shipinhao/caishen0923"
)
shipinhao.setCurrentIndex(caishen_index)
page._activate("视频号处理")
assert page.copies_spin.isHidden()
assert page.copies_label.isHidden()
assert not hasattr(page, "random_enhance")

window.close()
print("local processor integration: OK (8 platforms)")
