"""蒙版与横条 标签页。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGroupBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QFormLayout,
)

from config import AppConfig
from app.widgets.param_row import ParamRow


class MaskPage(QWidget):
    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self._rows: dict[str, ParamRow] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        root_layout = QVBoxLayout(inner)
        root_layout.setSpacing(16)

        # ── 矩形蒙版 ──
        mask_group = QGroupBox("矩形蒙版")
        mask_form = QFormLayout(mask_group)
        mask_form.setSpacing(10)

        mask_params = [
            ("启用矩形蒙版", "mask_enabled", "bool"),
            ("上下边距 %", "mask_margin_tb", "slider:0-50"),
            ("左右边距 %", "mask_margin_lr", "slider:0-50"),
            ("蒙版羽化", "mask_feather", "slider:0-100"),
        ]
        for label, key, ptype in mask_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            mask_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(mask_group)

        # ── 顶部蒙版 ──
        topmat_group = QGroupBox("顶部蒙版叠层")
        topmat_form = QFormLayout(topmat_group)
        topmat_form.setSpacing(10)
        topmat_params = [
            ("启用顶部蒙版", "top_step_enabled", "bool"),
            ("蒙版缩放 %", "top_scale", "slider:10-500"),
            ("蒙版透明度 %", "top_opacity", "slider:0-100"),
            ("蒙版羽化", "top_feather", "slider:0-100"),
        ]
        for label, key, ptype in topmat_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            topmat_form.addRow(row)
            self._rows[key] = row
        root_layout.addWidget(topmat_group)

        # ── 顶底横条 (非对称) ──
        bars_group = QGroupBox("顶底横条")
        bars_form = QFormLayout(bars_group)
        bars_form.setSpacing(10)
        bars_params = [
            ("启用横条", "bars_enabled", "bool"),
            ("顶部横条高度", "top_bar_height", "slider:10-1000"),
            ("顶部横条透明度 %", "top_bar_opacity", "slider:0-100"),
            ("底部横条高度", "bottom_bar_height", "slider:10-1000"),
            ("底部横条透明度 %", "bottom_bar_opacity", "slider:0-100"),
            ("双拼横条", "split_bars_enabled", "bool"),
            ("顶拼中线羽化", "tb_split_feather", "slider:0-100"),
            ("底拼中线羽化", "bb_split_feather", "slider:0-100"),
        ]
        for label, key, ptype in bars_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            bars_form.addRow(row)
            self._rows[key] = row
        root_layout.addWidget(bars_group)

        # ── 十字线 ──
        line_group = QGroupBox("十字线/横线")
        line_form = QFormLayout(line_group)
        line_form.setSpacing(10)
        line_params = [
            ("启用线条", "line_enabled", "bool"),
            ("线条样式", "line_style_choice", "combo:十字-点线,横线-虚线"),
            ("不透明度 %", "line_opacity", "slider:0-100"),
            ("竖线位置 %", "line_x", "slider:0-100"),
            ("横线位置 %", "line_y", "slider:0-100"),
            ("线条宽度", "line_width", "slider:1-20"),
        ]
        for label, key, ptype in line_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            line_form.addRow(row)
            self._rows[key] = row
        root_layout.addWidget(line_group)

        root_layout.addStretch()

        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


def _setattr(obj, key, value):
    try:
        if hasattr(obj, key):
            setattr(obj, key, value)
    except Exception:
        pass
