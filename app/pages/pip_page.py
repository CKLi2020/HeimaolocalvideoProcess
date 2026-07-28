"""画中画与动态 标签页。"""

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


class PipPage(QWidget):
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

        # ── 画中画 1 ──
        pip1_group = QGroupBox("画中画 1")
        pip1_form = QFormLayout(pip1_group)
        pip1_form.setSpacing(10)

        pip1_params = [
            ("启用画中画 1", "pip_enabled", "bool"),
            ("缩放 %", "pip_scale", "int:5-100"),
            ("透明度 %", "pip_opacity", "int:0-100"),
            ("X 位置 %", "pip_x", "int:-50-100"),
            ("Y 位置 %", "pip_y", "int:-50-100"),
            ("移动", "pip_move", "bool"),
        ]
        for label, key, ptype in pip1_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            pip1_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(pip1_group)

        # ── 画中画 2 ──
        pip2_group = QGroupBox("画中画 2")
        pip2_form = QFormLayout(pip2_group)
        pip2_form.setSpacing(10)

        pip2_params = [
            ("启用画中画 2", "pip2_enabled", "bool"),
            ("缩放 %", "pip2_scale", "int:5-100"),
            ("透明度 %", "pip2_opacity", "int:0-100"),
            ("X 位置 %", "pip2_x", "int:-50-100"),
            ("Y 位置 %", "pip2_y", "int:-50-100"),
            ("移动", "pip2_move", "bool"),
        ]
        for label, key, ptype in pip2_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            pip2_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(pip2_group)

        # ── 动态效果 ──
        motion_group = QGroupBox("动态效果")
        motion_form = QFormLayout(motion_group)
        motion_form.setSpacing(10)

        motion_params = [
            ("动态缩放幅度 %", "zoom_amp", "int:0-100"),
            ("左右晃动幅度 %", "sway_amp", "int:0-100"),
            ("随机晃动幅度 %", "shake_amp", "int:0-100"),
        ]
        for label, key, ptype in motion_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            motion_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(motion_group)
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
