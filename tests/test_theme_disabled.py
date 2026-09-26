"""置灰必须看得出来。

样式表里只要给某个控件写过颜色，Qt 就不再用调色板的 disabled 色 —— 不补
`:disabled` 规则的话 `setEnabled(False)` **功能上生效、画面上一点没变**。
「移动贴纸」页关掉开关要整页置灰、模板页选「随机」要灰掉固定模板那一行，
都踩过这个坑：断言 `isEnabled()` 是绿的，截图上却看不出来。

所以这里除了钉住 :disabled 规则在不在，还要真的渲染一遍比亮度。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QTabWidget

from app.theme import MIDNIGHT_QSS

# 会出现在置灰区块里的控件类型，逐一要求有 :disabled 规则。
# 注意 QLabel#previewHint 这类**按 id 上色**的标签**故意不列**：id 选择器
# 优先于伪类，置灰时它保持原色 —— 提示文字正是用来解释为什么灰的，该看得清。
REQUIRED = (
    "QLabel:disabled",
    "QGroupBox:disabled",
    "QGroupBox::title:disabled",
    "QLineEdit:disabled",
    "QSpinBox:disabled",
    "QComboBox:disabled",
    "QSlider::groove:horizontal:disabled",
    "QSlider::sub-page:horizontal:disabled",
    "QSlider::handle:horizontal:disabled",
    "QCheckBox:disabled",
    "QCheckBox::indicator:disabled",
    # 勾选图案不会从 :checked 继承，少了这条禁用后勾就没了
    "QCheckBox::indicator:checked:disabled",
    "QPushButton:disabled",
    # 按 id 上色的按钮：id 比伪类优先，不单独写就会「灰了还亮着」
    "QPushButton#browse:disabled",
    "QPushButton#danger:disabled",
    "QPushButton#accent:disabled",
)

missing = [sel for sel in REQUIRED if sel not in MIDNIGHT_QSS]
assert not missing, f"样式表里少了这些置灰规则：{missing}"


def _mean_brightness(widget) -> float:
    img = widget.grab().toImage()
    total = 0
    count = 0
    for y in range(0, img.height(), 7):
        for x in range(0, img.width(), 7):
            total += (img.pixel(x, y) >> 16) & 0xFF
            count += 1
    return total / max(1, count)


app = QApplication.instance() or QApplication([])

from app.main_window import MainWindow  # noqa: E402  (要在 QApplication 之后)
from config import AppConfig  # noqa: E402

window = MainWindow(AppConfig(), Path(__file__).resolve().parent.parent)
window.resize(1600, 950)
window.show()
page = window._pages["移动贴纸"]
switch = page._rows["moving_sticker_enabled"]
for tabs in window.findChildren(QTabWidget):
    for i in range(tabs.count()):
        if tabs.tabText(i) == "移动贴纸":
            tabs.setCurrentIndex(i)
app.processEvents()

# 开着：滑条是蓝的、勾是蓝的
switch._widget.setChecked(True)
app.processEvents()
on = _mean_brightness(page)

# 关掉：整页置灰，整个页面应当明显暗下来（不只是 isEnabled() 变成 False）
switch._widget.setChecked(False)
app.processEvents()
off = _mean_brightness(page)

assert window.config.moving_sticker_enabled is False
print(f"  开启/关闭 画面平均亮度：{on:.1f} / {off:.1f}")

# 阈值放宽：只要求「看得出来暗了」，不锁具体像素值。
if not off < on - 3:
    raise AssertionError(
        f"关掉「启用移动贴纸」后画面没明显变暗（{on:.1f} -> {off:.1f}）——"
        "多半是缺 :disabled 样式，setEnabled 在界面上看不出来"
    )

# 开关自己必须留着能点，否则关掉就再也开不回来
assert switch.isEnabled(), "关掉后开关自己也灰了，再也开不回来"

window.close()
print(f"theme disabled test: OK ({len(REQUIRED)} 条置灰规则)")
