"""开幕、封面与字幕 标签页。"""

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


class OpeningPage(QWidget):
    def __init__(self, config: AppConfig, section: str = "all", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self._rows: dict[str, ParamRow] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        root_layout = QVBoxLayout(inner)
        root_layout.setSpacing(16)

        # ── 开幕 ──
        kaimu_group = QGroupBox("开幕效果")
        kaimu_form = QFormLayout(kaimu_group)
        kaimu_form.setSpacing(10)

        kaimu_params = [
            ("启用开幕效果", "kaimu_enabled", "bool"),
            ("开幕方式", "kaimu_mode", "combo:上下开幕,左右开幕,黑屏开幕,素材-随机"),
            ("开幕速度 %", "kaimu_speed", "slider:10-500"),
        ]
        for label, key, ptype in kaimu_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            kaimu_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(kaimu_group)
        kaimu_group.setVisible(section in ("all", "cover"))

        # ── 封面 ──
        cover_group = QGroupBox("封面标题")
        cover_form = QFormLayout(cover_group)
        cover_form.setSpacing(10)

        cover_params = [
            ("启用封面", "cover_enabled", "bool"),
            ("标题跟随文件名", "cover_follow_name", "bool"),
            ("自定义标题文字", "cover_text", "text"),
            ("标题字号", "cover_size", "slider:10-200"),
            ("标题位置 Y %", "cover_y", "slider:0-100"),
        ]
        for label, key, ptype in cover_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            cover_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(cover_group)
        cover_group.setVisible(section in ("all", "cover"))

        # ── 字幕 ──
        sub_group = QGroupBox("字幕 (faster-whisper)")
        sub_form = QFormLayout(sub_group)
        sub_form.setSpacing(10)

        sub_params = [
            ("启用字幕", "subtitle_enabled", "bool"),
            ("导出 SRT", "subtitle_export_srt", "bool"),
            ("字幕模型", "subtitle_model", "combo:tiny,small,medium,large"),
            ("字幕样式", "subtitle_style", "combo:经典白字黑边,剪映式短句,秒剪风格"),
            ("字幕字号", "subtitle_font_size", "slider:12-72"),
            ("每行最大字数", "subtitle_max_chars", "slider:5-50"),
            ("字幕位置 Y %", "subtitle_pos_y", "slider:0-100"),
        ]
        for label, key, ptype in sub_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            sub_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(sub_group)
        sub_group.setVisible(section in ("all", "subtitle"))
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
