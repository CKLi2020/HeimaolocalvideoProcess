"""贴纸与扫光 标签页。"""

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


class StickerPage(QWidget):
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

        # ── 贯穿贴纸 ──
        sticker_group = QGroupBox("贯穿贴纸")
        sticker_form = QFormLayout(sticker_group)
        sticker_form.setSpacing(10)

        sticker_params = [
            ("启用贯穿贴纸", "sticker_enabled", "bool"),
            ("缩放 %", "sticker_scale", "int:5-200"),
            ("透明度 %", "sticker_opacity", "int:0-100"),
            ("X 位置 %", "sticker_x", "int:0-100"),
            ("Y 位置 %", "sticker_y", "int:0-100"),
            ("换组间隔 (秒)", "sticker_switch_sec", "int:0-120"),
        ]
        for label, key, ptype in sticker_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            sticker_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(sticker_group)

        # ── 移动贴纸 ──
        mover_group = QGroupBox("移动贴纸")
        mover_form = QFormLayout(mover_group)
        mover_form.setSpacing(10)

        mover_params = [
            ("启用移动贴纸", "moving_sticker_enabled", "bool"),
            ("移动周期 (秒)", "moving_sticker_period", "int:1-60"),
        ]
        for label, key, ptype in mover_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            mover_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(mover_group)

        # ── 扫光 ──
        sl_group = QGroupBox("扫光效果")
        sl_form = QFormLayout(sl_group)
        sl_form.setSpacing(10)

        sl_params = [
            ("启用扫光", "scanlight_enabled", "bool"),
            ("透明度 %", "scanlight_opacity", "int:0-100"),
            ("扫光速度 %", "scanlight_speed", "int:10-500"),
        ]
        for label, key, ptype in sl_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            sl_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(sl_group)
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
