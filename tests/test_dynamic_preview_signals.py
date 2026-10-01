"""Verify every parameter control schedules a dynamic preview refresh."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QSpinBox

from app.main_window import MainWindow
from app.widgets.param_row import ParamRow
from config import AppConfig


app = QApplication.instance() or QApplication([])
window = MainWindow(AppConfig(), Path(__file__).resolve().parent.parent)
window.show()
app.processEvents()

# 走 window._pages 而不是 findChildren(ParamRow)：右栏有几个页已经从标签栏
# 收起（「贴图」「人脸遮挡」），页对象仍在 _pages 里、参数行照样参与联动，
# 但它们不再是标签栏的子控件，findChildren 找不到——用 findChildren 会漏掉
# 一整页的参数，还会随着标签页增减时红时绿。_preview 的联动就是按 _pages
# 遍历的（见 _wire_params_to_preview），所以这里按同一份来源枚举才对齐。
all_rows = [
    (name, key, row)
    for name, page in window._pages.items()
    for key, row in getattr(page, "_rows", {}).items()
    # 声音参数不改变画面，无需重新生成可视化预览。
    if name != "声音处理"
    # 文件夹行（FolderRow）不用 _widget，也不走 value_changed，跳过。
    if isinstance(row, ParamRow)
]
assert all_rows, "no ParamRow found via window._pages"

changed = 0
failed = []
for name, key, row in all_rows:
    widget = row._widget
    new_value = None
    if isinstance(widget, QSpinBox):
        new_value = widget.value() + 1 if widget.value() < widget.maximum() else widget.value() - 1
    elif isinstance(widget, QCheckBox):
        new_value = not widget.isChecked()
    elif isinstance(widget, QComboBox) and widget.count() > 1:
        new_value = (widget.currentIndex() + 1) % widget.count()
    if new_value is None:
        continue

    window._preview._debounce.stop()
    if isinstance(widget, QSpinBox):
        widget.setValue(new_value)
    elif isinstance(widget, QCheckBox):
        widget.setChecked(new_value)
    else:
        widget.setCurrentIndex(new_value)
    app.processEvents()
    changed += 1
    if not window._preview._debounce.isActive():
        failed.append(f"{name}.{key}")

window.close()
assert changed > 100, changed
assert not failed, failed
print(f"dynamic preview signals: OK ({changed} controls)")
