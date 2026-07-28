"""暗色主题样式表 (QSS)。"""
from __future__ import annotations


DARK_QSS = """
/* ── 全局 ── */
QWidget {
    background-color: #0f1419;
    color: #e1e8ed;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow {
    background-color: #0f1419;
}

/* ── 标签页 ── */
QTabWidget::pane {
    border: 1px solid #2d3a47;
    background-color: #16202a;
    border-radius: 6px;
    margin-top: -1px;
}
QTabBar::tab {
    background-color: #1a2632;
    color: #8899a6;
    padding: 10px 20px;
    border: 1px solid #2d3a47;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #16202a;
    color: #6366f1;
    border-bottom: 2px solid #6366f1;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background-color: #1f2d3b;
    color: #c4c9ef;
}

/* ── 按钮 ── */
QPushButton {
    background-color: #1e2d3d;
    color: #e1e8ed;
    border: 1px solid #3a4a5c;
    border-radius: 4px;
    padding: 7px 16px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #263545;
    border-color: #4a5c72;
}
QPushButton:pressed {
    background-color: #16222e;
}
QPushButton#accent {
    background-color: #6366f1;
    border-color: #6366f1;
    color: white;
    font-weight: bold;
    padding: 10px 24px;
    font-size: 14px;
}
QPushButton#accent:hover {
    background-color: #818cf8;
}
QPushButton#danger {
    background-color: #3d2026;
    border-color: #5c3a40;
    color: #fda4af;
}
QPushButton#danger:hover {
    background-color: #4d2830;
}
QPushButton#browse {
    background-color: #1e2d3d;
    padding: 7px 12px;
    min-width: 56px;
}

/* ── 输入框 ── */
QLineEdit {
    background-color: #1a2632;
    color: #f0f4f8;
    border: 1px solid #3a4a5c;
    border-radius: 4px;
    padding: 6px 10px;
    selection-background-color: #6366f1;
}
QLineEdit:focus {
    border-color: #6366f1;
}
QSpinBox {
    background-color: #1a2632;
    color: #f0f4f8;
    border: 1px solid #3a4a5c;
    border-radius: 4px;
    padding: 6px 8px;
}
QSpinBox:focus {
    border-color: #6366f1;
}

/* ── 复选框 ── */
QCheckBox {
    color: #c4c9d0;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #4a5c72;
    border-radius: 3px;
    background-color: #1a2632;
}
QCheckBox::indicator:checked {
    background-color: #6366f1;
    border-color: #6366f1;
}
QCheckBox::indicator:hover {
    border-color: #6366f1;
}

/* ── 分组框 ── */
QGroupBox {
    border: 1px solid #2d3a47;
    border-radius: 6px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: bold;
    color: #a0b0c0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
}

/* ── 滚动条 ── */
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    background-color: #16202a;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #3a4a5c;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #4a5c72;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* ── 进度条 ── */
QProgressBar {
    background-color: #1a2632;
    border: 1px solid #3a4a5c;
    border-radius: 4px;
    height: 10px;
    text-align: center;
    font-size: 11px;
    color: #a0b0c0;
}
QProgressBar::chunk {
    background-color: #6366f1;
    border-radius: 3px;
}

/* ── 标签 ── */
QLabel#title {
    font-size: 20px;
    font-weight: bold;
    color: #f0f4f8;
}
QLabel#subtitle {
    font-size: 12px;
    color: #6b7f94;
}
QLabel#status {
    font-size: 12px;
    padding: 6px 14px;
    background-color: #162232;
    border-radius: 12px;
    color: #86efac;
}

/* ── 日志 ── */
QTextEdit {
    background-color: #060d15;
    color: #a7f3d0;
    border: 1px solid #1f2d3b;
    border-radius: 4px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    padding: 10px;
}

/* ── 预览画布 ── */
QLabel#preview {
    background-color: #060d15;
    border: 1px solid #2d3a47;
    border-radius: 6px;
}

/* ── 分割线 ── */
QSplitter::handle {
    background-color: #2d3a47;
    width: 1px;
}

/* ── 下拉框 ── */
QComboBox {
    background-color: #1a2632;
    color: #f0f4f8;
    border: 1px solid #3a4a5c;
    border-radius: 4px;
    padding: 6px 10px;
    min-width: 120px;
}
QComboBox:hover {
    border-color: #4a5c72;
}
QComboBox QAbstractItemView {
    background-color: #1a2632;
    color: #e1e8ed;
    selection-background-color: #6366f1;
    border: 1px solid #3a4a5c;
}
"""
