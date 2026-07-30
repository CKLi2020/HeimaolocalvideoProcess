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

changed = 0
failed = []
for index, row in enumerate(window.findChildren(ParamRow)):
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
        failed.append(index)

window.close()
assert changed > 100, changed
assert not failed, failed
print(f"dynamic preview signals: OK ({changed} controls)")
