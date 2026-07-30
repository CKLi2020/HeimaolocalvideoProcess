"""BlackCat FlowCut visual theme."""

DARK_QSS = """
/* Foundation */
QWidget {
    background: #0d1326;
    color: #e8eeff;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 12px;
}
QMainWindow { background: #080d1b; }
QFrame#panel {
    background: #151f38;
    border: 1px solid #2a3a60;
    border-radius: 8px;
}
QFrame#sidebar, QFrame#channelBar {
    background: #0a1022;
    border: 1px solid #202e4e;
    border-radius: 8px;
}

/* Typography */
QLabel { color: #dce5fb; }
QLabel#brand {
    color: #ffffff;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#channelBrand {
    color: #ffffff;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#brandSub {
    color: #42dcff;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#status {
    color: #48e6ff;
    font-weight: 700;
    padding: 4px 8px;
}

/* Sections */
QGroupBox {
    background: #151f38;
    border: 1px solid #30436d;
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 13px;
    padding: 0 7px;
    color: #7de7ff;
    background: #151f38;
}

/* Inputs */
QLineEdit, QSpinBox, QComboBox {
    background: #0e1830;
    color: #f4f7ff;
    border: 1px solid #40547f;
    border-radius: 6px;
    padding: 5px 9px;
    min-height: 22px;
    selection-background-color: #6b7cff;
}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: #647aa9; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    background: #111e3a;
    border: 1px solid #42dcff;
}
QComboBox QAbstractItemView {
    background: #111a31;
    color: #eef3ff;
    border: 1px solid #40547f;
    outline: 0;
    selection-background-color: #334d87;
}

/* Buttons */
QPushButton {
    background: #202e4d;
    color: #eaf0ff;
    border: 1px solid #3b507e;
    border-radius: 6px;
    padding: 6px 13px;
    min-height: 24px;
    font-weight: 600;
}
QPushButton:hover {
    background: #293a61;
    color: #ffffff;
    border-color: #6f8dcc;
}
QPushButton:pressed {
    background: #172440;
    padding-top: 7px;
    padding-bottom: 5px;
}
QPushButton:disabled {
    background: #151d31;
    color: #66728d;
    border-color: #28344f;
}
QPushButton#accent {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #557dff, stop:1 #42b8ff
    );
    color: #ffffff;
    border: 1px solid #79cfff;
    font-weight: 700;
}
QPushButton#accent:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #6a8eff, stop:1 #55c8ff
    );
}
QPushButton#danger {
    background: #2b1833;
    color: #ff91d5;
    border: 1px solid #9d3c82;
}
QPushButton#danger:hover {
    background: #432044;
    color: #ffc2e9;
    border-color: #f052ba;
}
QPushButton#browse { min-width: 52px; padding-left: 9px; padding-right: 9px; }

/* Channel navigation */
QPushButton#channelButton {
    background: #111b33;
    color: #cbd6ed;
    border: 1px solid #2d4068;
    border-radius: 7px;
    padding: 10px 10px;
    text-align: left;
    min-height: 25px;
}
QPushButton#channelButton:hover {
    color: #ffffff;
    background: #172743;
    border-color: #4a6598;
}
QPushButton#channelButton:checked {
    color: #ffffff;
    background: #2a2149;
    border: 1px solid #f052ba;
    border-left: 4px solid #f052ba;
}

/* Toggles and sliders */
QCheckBox { color: #dce5fb; spacing: 7px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    background: #0d172c;
    border: 1px solid #52668f;
    border-radius: 4px;
}
QCheckBox::indicator:hover { border-color: #42dcff; }
QCheckBox::indicator:checked {
    background: #42dcff;
    border-color: #8deeff;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #0b1428;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #627fff, stop:1 #42dcff
    );
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #42dcff;
    width: 13px;
    margin: -6px 0;
    border-radius: 7px;
}

/* Tabs */
QTabWidget::pane {
    background: #111a31;
    border: 1px solid #2b3e65;
    border-radius: 7px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #8fa0bf;
    padding: 9px 5px 7px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 11px;
    font-weight: 600;
}
QTabBar::tab:hover { color: #d9e5ff; }
QTabBar::tab:selected {
    color: #ffffff;
    background: #1b2947;
    border-bottom: 2px solid #42dcff;
}

/* Logs, preview and progress */
QTextEdit {
    background: #070c18;
    color: #a9edff;
    border: 1px solid #263a61;
    border-radius: 7px;
    font-family: "Cascadia Mono", Consolas;
    font-size: 11px;
    padding: 8px;
}
QLabel#preview {
    background: #040711;
    border: 1px solid #2d426d;
    border-radius: 7px;
}
QProgressBar {
    background: #0b1427;
    color: #eaf5ff;
    border: 1px solid #2d426d;
    border-radius: 5px;
    height: 11px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #627fff, stop:1 #42dcff
    );
    border-radius: 4px;
}

/* Chrome */
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    width: 8px;
    background: #0a1224;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #40547e;
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: #586d9a; }
QSplitter::handle { background: #1f3154; width: 3px; }
QToolTip {
    background: #182541;
    color: #ffffff;
    border: 1px solid #42dcff;
    padding: 5px;
}
"""

LIGHT_QSS = DARK_QSS
