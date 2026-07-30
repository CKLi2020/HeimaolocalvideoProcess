"""BlackCat cyber-navy Qt theme."""

DARK_QSS = """
QWidget {
    background: #151b34;
    color: #f3f6ff;
    font-family: "Microsoft YaHei UI";
    font-size: 12px;
}
QMainWindow { background: #10152b; }
QFrame#panel, QGroupBox {
    background: #2b395c;
    border: 1px solid #7085b7;
    border-radius: 10px;
}
QFrame#sidebar {
    background: #11172f;
    border: 1px solid #28375f;
    border-radius: 10px;
}
QFrame#channelBar {
    background: #0e142b;
    border: 1px solid #28375f;
    border-radius: 10px;
}
QLabel#channelBrand {
    color: #ffffff;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 2px;
}
QPushButton#channelButton {
    background: #182440;
    color: #eef3ff;
    border: 1px solid #526b9f;
    border-radius: 9px;
    padding: 10px 9px;
    text-align: left;
    min-height: 25px;
}
QPushButton#channelButton:hover {
    color: #28e8ff;
    border-color: #28e8ff;
}
QPushButton#channelButton:checked {
    background: #3b285c;
    color: #ffffff;
    border: 1px solid #f43bb5;
}
QLabel#brand {
    color: #ffffff;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#brandSub {
    color: #20e7ff;
    font-size: 10px;
    font-weight: 700;
}
QLabel#status { color: #27f3ff; font-weight: 700; }
QGroupBox {
    margin-top: 13px;
    padding: 15px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: #dbe6ff;
}
QLineEdit, QSpinBox, QComboBox {
    background: #3a496d;
    color: #ffffff;
    border: 1px solid #8da5da;
    border-radius: 8px;
    padding: 5px 9px;
    min-height: 22px;
    selection-background-color: #d82aa4;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #29e6ff;
    background: #405176;
}
QComboBox QAbstractItemView {
    background: #263454;
    color: #ffffff;
    border: 1px solid #7e95c7;
    selection-background-color: #d82aa4;
}
QPushButton {
    background: #3b4a70;
    color: #f7f9ff;
    border: 1px solid #8399cc;
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 24px;
    font-weight: 600;
}
QPushButton:hover {
    background: #465983;
    border-color: #28e8ff;
}
QPushButton:pressed { background: #263858; }
QPushButton:disabled { color: #7d88a5; border-color: #53617e; }
QPushButton#accent {
    background: #5d9ff0;
    color: white;
    border-color: #7bb7ff;
    font-weight: 700;
}
QPushButton#accent:hover { background: #6aafff; }
QPushButton#danger {
    background: #3d294f;
    color: #ff79cc;
    border-color: #d82aa4;
}
QPushButton#browse { min-width: 52px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    background: #273554;
    border: 1px solid #879ac5;
    border-radius: 4px;
}
QCheckBox::indicator:checked {
    background: #16d5e8;
    border-color: #6ff5ff;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #1d2948;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #25dff2;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #f6fbff;
    border: 2px solid #25dff2;
    width: 14px;
    margin: -6px 0;
    border-radius: 8px;
}
QTabWidget::pane {
    background: #263453;
    border: 1px solid #7085b7;
    border-radius: 9px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #cbd6ef;
    padding: 8px 5px;
    border: 1px solid transparent;
    font-size: 11px;
    font-weight: 600;
}
QTabBar::tab:hover { color: #28e8ff; }
QTabBar::tab:selected {
    background: #d82aa4;
    color: white;
    border-color: #ff65ca;
    border-radius: 7px;
}
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 9px; background: #18213d; border-radius: 4px; }
QScrollBar::handle:vertical {
    background: #6479a8;
    border-radius: 4px;
    min-height: 32px;
}
QTextEdit {
    background: #0a1024;
    color: #8ff7ff;
    border: 1px solid #536b9f;
    border-radius: 8px;
    font-family: Consolas;
    font-size: 11px;
    padding: 7px;
}
QLabel#preview {
    background: #060914;
    border: 1px solid #5d74a7;
    border-radius: 8px;
}
QProgressBar {
    background: #192441;
    color: white;
    border: 1px solid #536b9f;
    border-radius: 6px;
    height: 12px;
    text-align: center;
}
QProgressBar::chunk { background: #22e3f2; border-radius: 5px; }
QSplitter::handle { background: #34466f; width: 3px; }
QToolTip {
    background: #202d4b;
    color: white;
    border: 1px solid #28e8ff;
}
"""

# Compatibility for existing import.
LIGHT_QSS = DARK_QSS
