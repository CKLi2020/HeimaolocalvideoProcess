"""文件夹选择行：QLineEdit + "选择"按钮 + 可选状态指示。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
    QFileDialog,
)
from PySide6.QtCore import Signal


class FolderRow(QWidget):
    """一行：标签 | 路径输入框 | 选择按钮"""

    path_changed = Signal(str)

    def __init__(
        self,
        placeholder: str = "",
        initial: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._initial_dir = initial
        self.setMinimumHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setText(initial)
        self.edit.textChanged.connect(self.path_changed.emit)
        layout.addWidget(self.edit, stretch=1)

        btn = QPushButton("选择")
        btn.setObjectName("browse")
        btn.setFixedWidth(64)
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    @property
    def path(self) -> str:
        return self.edit.text().strip()

    @path.setter
    def path(self, value: str) -> None:
        self.edit.setText(value)

    def _browse(self) -> None:
        start = self.path or self._initial_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "选择文件夹", start,
        )
        if folder:
            self.edit.setText(folder)
            self.path_changed.emit(folder)
