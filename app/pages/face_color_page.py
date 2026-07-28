"""人脸、调色与后处理 标签页。"""

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


class FaceColorPage(QWidget):
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

        # ── 人脸模糊 ──
        face_group = QGroupBox("人脸自动模糊")
        face_form = QFormLayout(face_group)
        face_form.setSpacing(10)

        face_params = [
            ("启用人脸模糊", "face_blur_enabled", "bool"),
            ("模糊强度", "face_blur_strength", "int:1-100"),
            ("检测间隔帧", "face_detect_every", "int:1-30"),
        ]
        for label, key, ptype in face_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            face_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(face_group)

        # ── 调色 ──
        color_group = QGroupBox("画面调色")
        color_form = QFormLayout(color_group)
        color_form.setSpacing(10)

        color_params = [
            ("预设滤镜", "filter_name", "combo:无,晴川,暖阳,复古,黑白,冷色,胶片,鲜明,淡雅"),
            ("滤镜强度", "filter_strength", "int:0-100"),
            ("亮度", "brightness", "int:-100-100"),
            ("对比度", "contrast", "int:-100-100"),
            ("饱和度", "saturation", "int:-100-100"),
            ("色温", "temperature", "int:-100-100"),
            ("暗角", "vignette", "int:0-100"),
        ]
        for label, key, ptype in color_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            color_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(color_group)

        # ── MP4 后处理 ──
        mp4_group = QGroupBox("MP4 后处理 (元数据编辑)")
        mp4_form = QFormLayout(mp4_group)
        mp4_form.setSpacing(10)

        mp4_params = [
            ("启用 MP4 后处理", "mp4_enabled", "bool"),
            ("二次编码 H.265", "mp4_hevc", "bool"),
            ("随机分辨率填充", "mp4_random_size", "bool"),
            ("Track ID 跟随", "mp4_id_follow", "bool"),
            ("视频 Layer", "mp4_layer_video", "int:0-65535"),
            ("音频 Layer", "mp4_layer_audio", "int:0-65535"),
            ("视频轨延迟 (ms)", "mp4_elst_ms", "int:0-99999"),
        ]
        for label, key, ptype in mp4_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            mp4_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(mp4_group)
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
