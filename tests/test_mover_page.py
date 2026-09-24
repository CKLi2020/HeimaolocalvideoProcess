"""「移动贴纸」页：数量滑条与逐条轨道必须始终一致，参数只在界面上填。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.pages.mover_page import MoverPage
from app.widgets.param_row import ParamRow
from config import AppConfig


def _layers(page: MoverPage) -> list[dict]:
    layers = json.loads(page.config.mover_layers_json or "[]")
    assert isinstance(layers, list)
    return layers


def _count_row(page: MoverPage) -> ParamRow:
    return page._rows["mover_count"]


app = QApplication.instance() or QApplication([])
config = AppConfig()
page = MoverPage(config)
window = MainWindow(config, Path(__file__).resolve().parent.parent)

# ── 数量滑条 = 列表条数 ──
assert config.mover_count == len(_layers(page)) == 5, (
    config.mover_count, len(_layers(page))
)

_count_row(page)._widget.setValue(3)          # 像用户拖滑条那样（会发信号）
assert config.mover_count == 3, config.mover_count
assert len(_layers(page)) == 3, len(_layers(page))

_count_row(page)._widget.setValue(9)
assert config.mover_count == 9, config.mover_count
assert len(_layers(page)) == 9, len(_layers(page))

# 已经改过的行不能被补齐动作覆盖掉
layers = _layers(page)
layers[0]["scale"] = 77
page._save_layers(layers)
_count_row(page)._widget.setValue(9)          # 数量没变，重设一次
assert _layers(page)[0]["scale"] == 77, _layers(page)[0]

_count_row(page)._widget.setValue(4)
assert _layers(page)[0]["scale"] == 77, _layers(page)[0]
assert len(_layers(page)) == 4

# ── 每条轨道都有自己的完整参数 ──
for layer in _layers(page):
    missing = {"scale", "opacity", "x", "y", "period"} - set(layer)
    assert not missing, (layer, missing)

# ── 界面上的每一条轨道都要能改到 config ──
row = page._rows["mover_layer_1_period"]
row._widget.setValue(23)
assert _layers(page)[1]["period"] == 23, _layers(page)[1]

# ── 随机位置开着时，位置那两行置灰（填了也不生效） ──
config.mover_random = True
page._rebuild_layers()
for key in ("x", "y"):
    assert not page._rows[f"mover_layer_0_{key}"].isEnabled(), key
for key in ("scale", "opacity", "period"):
    assert page._rows[f"mover_layer_0_{key}"].isEnabled(), key

config.mover_random = False
page._rebuild_layers()
for key in ("x", "y"):
    assert page._rows[f"mover_layer_0_{key}"].isEnabled(), key

# ── 关掉随机后，出片必须原样照用界面上的位置 ──
config.mover_random = False
layers = _layers(page)
layers[0]["x"], layers[0]["y"] = -12.0, -34.0
page._save_layers(layers)
from engine.ffmpeg_builder import build_mover_layers

built = build_mover_layers(
    config.mover_count, _layers(page), config.mover_scale,
    config.mover_opacity, config.moving_sticker_period, roll_positions=False,
)
assert (built[0]["x"], built[0]["y"]) == (-12.0, -34.0), built[0]

# ── 开着随机则只掷位置，缩放/不透明度/周期照抄 ──
rolled = build_mover_layers(
    config.mover_count, _layers(page), config.mover_scale,
    config.mover_opacity, config.moving_sticker_period, roll_positions=True,
)
assert (rolled[0]["scale"], rolled[0]["opacity"]) == (
    _layers(page)[0]["scale"], _layers(page)[0]["opacity"]
), rolled[0]
assert (rolled[0]["x"], rolled[0]["y"]) != (-12.0, -34.0), rolled[0]
assert not rolled[0]["x"] or rolled[0]["x"] < 0

# ── 删除按钮：至少留一条 ──
while len(_layers(page)) > 1:
    page._delete_layer(0)
assert len(_layers(page)) == 1 and config.mover_count == 1
page._delete_layer(0)
assert len(_layers(page)) == 1, _layers(page)

# ── 界面改的必须落进 config ──
# 这一组是补的回归：上面所有用例都是直接改 config（`config.mover_random = False`），
# 绕过了控件，于是「在界面上改了不写进 config」这个 bug 一条都测不到 ——
# 开关点了没反应、周期改了不生效，界面上全看不出来。
def _click(key, value):
    """像用户那样操作控件（走信号；setChecked 只在值真变了才发信号）。"""
    widget = page._rows[key]._widget
    if isinstance(value, bool):
        widget.setChecked(not value)
        widget.setChecked(value)
    else:
        widget.setValue(value)


config.moving_sticker_enabled = True
config.mover_random = True
config.moving_sticker_period = 8
_click("moving_sticker_enabled", False)
assert config.moving_sticker_enabled is False, "开关点了没写进 config"
_click("mover_random", False)
assert config.mover_random is False, "「每次随机轨道」改了没写进 config"
_click("moving_sticker_period", 31)
assert config.moving_sticker_period == 31, "「默认周期」改了没写进 config"

# ── 关掉就整页置灰，但开关自己必须留着能点 ──
_click("moving_sticker_enabled", True)   # 先确保是开着的
_click("moving_sticker_enabled", False)
assert page._rows["moving_sticker_enabled"].isEnabled(), (
    "开关自己也被灰掉了 —— 关掉之后再也开不回来"
)
for key in ("moving_sticker_folder", "mover_count", "mover_random",
            "moving_sticker_period"):
    assert not page._rows[key].isEnabled(), key
assert not page._add_button.isEnabled()
assert not any(box.isEnabled() for box in page._layer_boxes), "贴纸组该整组灰"
for key in ("scale", "opacity", "x", "y", "period"):
    assert not page._rows[f"mover_layer_0_{key}"].isEnabled(), key
assert "已关闭" in page._hint.text(), page._hint.text()

# ── 再打开：全部恢复，且「随机轨道」那条置灰规则还在（关的时候别把它弄丢） ──
_click("moving_sticker_enabled", True)
_click("mover_random", True)
for key in ("moving_sticker_folder", "mover_count", "mover_random",
            "moving_sticker_period"):
    assert page._rows[key].isEnabled(), key
assert page._add_button.isEnabled()
assert all(box.isEnabled() for box in page._layer_boxes)
assert not page._rows["mover_layer_0_x"].isEnabled(), "重开后随机置灰规则丢了"
assert page._rows["mover_layer_0_scale"].isEnabled()
assert "随机轨道" in page._hint.text(), page._hint.text()

# 关掉开关不会顺手清空轨道（再开回来还是原来那几条）
_click("moving_sticker_enabled", False)
assert len(_layers(page)) >= 1, "关掉不该清空轨道"
_click("moving_sticker_enabled", True)

# ── 左侧不再有「移动贴图文件夹」，右侧这一页有文件夹选择 ──
assert "moving_sticker_folder" not in window._files_page._rows
assert hasattr(page._rows["moving_sticker_folder"], "path_changed")
page._rows["moving_sticker_folder"].path = "D:/贴图目录"
assert config.moving_sticker_folder == "D:/贴图目录", config.moving_sticker_folder

window.close()
print("mover page test: OK")
