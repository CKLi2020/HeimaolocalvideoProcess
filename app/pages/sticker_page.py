"""贴纸与扫光标签页。"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig
from app.widgets.param_row import ParamRow


class StickerPage(QWidget):
    preview_changed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self._rows: dict[str, ParamRow] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self._layout = QVBoxLayout(inner)
        self._layout.setSpacing(12)

        enabled = ParamRow("启用贴纸", "bool", config.sticker_enabled)
        enabled.value_changed.connect(
            lambda value: self._set_config("sticker_enabled", value)
        )
        self._rows["sticker_enabled"] = enabled
        self._layout.addWidget(enabled)

        self._layers_layout = QVBoxLayout()
        self._layers_layout.setSpacing(12)
        self._layout.addLayout(self._layers_layout)

        add_button = QPushButton("＋ 增加贴纸")
        add_button.clicked.connect(self._add_layer)
        self._layout.addWidget(add_button)

        mover_group = QGroupBox("移动贴纸")
        mover_form = QFormLayout(mover_group)
        for label, key, ptype in (
            ("启用移动贴纸", "moving_sticker_enabled", "bool"),
            ("移动周期（秒）", "moving_sticker_period", "slider:1-60"),
        ):
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(
                lambda value, name=key: self._set_config(name, value)
            )
            mover_form.addRow(row)
            self._rows[key] = row
        self._layout.addWidget(mover_group)

        scan_group = QGroupBox("扫光效果")
        scan_form = QFormLayout(scan_group)
        for label, key, ptype in (
            ("启用扫光", "scanlight_enabled", "bool"),
            ("透明度 %", "scanlight_opacity", "slider:0-100"),
            ("扫光速度 %", "scanlight_speed", "slider:10-500"),
        ):
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(
                lambda value, name=key: self._set_config(name, value)
            )
            scan_form.addRow(row)
            self._rows[key] = row
        self._layout.addWidget(scan_group)
        self._layout.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._rebuild_layers()

    def _layers(self) -> list[dict]:
        try:
            layers = json.loads(self.config.sticker_layers_json)
            if isinstance(layers, list):
                return layers
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def _save_layers(self, layers: list[dict]) -> None:
        self.config.sticker_layers_json = json.dumps(layers, ensure_ascii=False)
        self.preview_changed.emit()

    def _rebuild_layers(self) -> None:
        while self._layers_layout.count():
            item = self._layers_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for index, layer in enumerate(self._layers()):
            group = QGroupBox(f"贴纸 {index + 1}")
            form = QFormLayout(group)
            for label, key, ptype, default in (
                ("图片缩放 %", "scale", "slider:5-200", 100),
                ("不透明度 %", "opacity", "slider:0-100", 100),
                ("水平位置 %", "x", "slider:-50-50", 0),
                ("垂直位置 %", "y", "slider:-50-50", 0),
            ):
                row = ParamRow(label, ptype, layer.get(key, default))
                row.value_changed.connect(
                    lambda value, i=index, name=key: self._update_layer(i, name, value)
                )
                form.addRow(row)
            delete_button = QPushButton("删除此贴纸")
            delete_button.setObjectName("danger")
            delete_button.clicked.connect(
                lambda checked=False, i=index: self._delete_layer(i)
            )
            form.addRow(delete_button)
            self._layers_layout.addWidget(group)

    def _update_layer(self, index: int, key: str, value) -> None:
        layers = self._layers()
        if index < len(layers):
            layers[index][key] = value
            self._save_layers(layers)

    def _add_layer(self) -> None:
        layers = self._layers()
        layers.append({"scale": 100, "opacity": 100, "x": 0, "y": 0})
        self._save_layers(layers)
        self._rebuild_layers()

    def _delete_layer(self, index: int) -> None:
        layers = self._layers()
        if index < len(layers):
            layers.pop(index)
            self._save_layers(layers)
            self._rebuild_layers()

    def _set_config(self, key: str, value) -> None:
        setattr(self.config, key, value)
        self.preview_changed.emit()
