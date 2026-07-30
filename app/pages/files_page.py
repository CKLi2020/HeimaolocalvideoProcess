"""文件与批量 标签页。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGroupBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QFormLayout,
)
from PySide6.QtCore import Signal

from config import AppConfig
from app.widgets.folder_row import FolderRow
from app.widgets.param_row import ParamRow


class FilesPage(QWidget):
    paths_changed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self._rows: dict[str, FolderRow | ParamRow] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        root_layout = QVBoxLayout(inner)
        root_layout.setSpacing(16)

        # ── 文件夹 ──
        folder_group = QGroupBox("文件夹设置")
        folder_form = QFormLayout(folder_group)
        folder_form.setSpacing(10)

        folders = [
            ("主素材文件夹", "main_folder"),
            ("辅助视频文件夹", "background_folder"),
            ("贴纸文件夹", "sticker_folder"),
            ("移动贴图文件夹", "moving_sticker_folder"),
            ("扫光文件夹", "scanlight_folder"),
            ("开幕素材文件夹", "kaimu_folder"),
            ("输出文件夹", "output_folder"),
        ]
        for label, key in folders:
            row = FolderRow(placeholder=f"选择{label}...", initial=str(getattr(config, key, "")))
            row.path_changed.connect(lambda v, k=key: self._set_folder(k, v))
            folder_form.addRow(label, row)
            self._rows[key] = row

        root_layout.addWidget(folder_group)

        root_layout.addStretch()

        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _set_folder(self, key: str, value: str) -> None:
        setattr(self.config, key, value)
        self.paths_changed.emit()


def _setattr(obj, key, value):
    """安全设置属性。"""
    try:
        if hasattr(obj, key):
            setattr(obj, key, value)
    except Exception:
        pass
