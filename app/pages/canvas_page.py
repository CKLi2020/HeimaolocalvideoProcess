"""画布与编码 标签页。"""

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


class CanvasPage(QWidget):
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

        # ── 画布 ──
        canvas_group = QGroupBox("画布设置")
        canvas_form = QFormLayout(canvas_group)
        canvas_form.setSpacing(10)

        canvas_params = [
            ("输出分辨率", "resolution", "text"),
            ("输出帧率", "fps", "slider:1-120"),
            ("主视频缩放 %", "main_scale", "slider:10-500"),
            ("主视频完整适配", "main_fit", "bool"),
            ("辅助视频缩放 %", "aux_scale", "slider:10-500"),
            ("辅助视频速度 %", "aux_speed", "slider:10-500"),
        ]
        for label, key, ptype in canvas_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            canvas_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(canvas_group)

        # ── 编码 ──
        encode_group = QGroupBox("编码设置")
        encode_form = QFormLayout(encode_group)
        encode_form.setSpacing(10)

        encode_params = [
            ("启用 GPU 加速", "gpu", "bool"),
            ("H.265 (HEVC)", "hevc", "bool"),
            ("CRF 质量", "crf", "slider:0-51"),
            ("编码速度预设", "preset", "combo:ultrafast,superfast,veryfast,faster,fast,medium,slow,slower,veryslow"),
        ]
        for label, key, ptype in encode_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            encode_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(encode_group)
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
