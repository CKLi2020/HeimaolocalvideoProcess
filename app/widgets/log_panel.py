"""日志面板：只读 QTextEdit，支持追加彩色文本。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QTextEdit, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtGui import QTextCursor, QColor
from PySide6.QtCore import Qt


class LogPanel(QWidget):
    """带标题的日志输出面板。"""

    def __init__(self, title: str = "任务日志", parent: Optional[QWidget] = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header_layout = QHBoxLayout()
        header = QLabel(title)
        header.setObjectName("logHeader")
        self.header_layout.addWidget(header)
        self.header_layout.addStretch()
        layout.addLayout(self.header_layout)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setMinimumHeight(120)
        layout.addWidget(self._text)

    def append(self, text: str, color: str = "#6ee7b7") -> None:
        """追加一行日志。"""
        self._text.moveCursor(QTextCursor.End)
        fmt = self._text.currentCharFormat()
        fmt.setForeground(QColor(color))
        self._text.setCurrentCharFormat(fmt)
        self._text.append(text)

    def clear(self) -> None:
        self._text.clear()

    def set_text(self, text: str) -> None:
        self._text.setPlainText(text)
