"""Reference-style light Qt theme."""

LIGHT_QSS = """
QWidget {
    background: #f5f5f5;
    color: #202124;
    font-family: "Microsoft YaHei UI";
    font-size: 12px;
}
QMainWindow { background: #f3f3f3; }
QFrame#panel, QGroupBox {
    background: #eeeeee;
    border: 1px solid #d3d3d3;
    border-radius: 6px;
}
QGroupBox {
    margin-top: 10px;
    padding: 12px 8px 8px;
    color: #ff5b57;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QLineEdit, QSpinBox, QComboBox {
    background: white;
    border: 1px solid #c7c7c7;
    border-radius: 4px;
    padding: 4px 7px;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #43ae55; }
QPushButton {
    background: white;
    border: 1px solid #c9c9c9;
    border-radius: 4px;
    padding: 5px 12px;
    min-height: 22px;
}
QPushButton:hover { background: #f1fff3; border-color: #45b65a; }
QPushButton#accent { background: #49b75a; color: white; border-color: #49b75a; font-weight: bold; }
QPushButton#accent:hover { background: #3da64d; }
QPushButton#danger { color: #ff514c; }
QPushButton#browse { min-width: 46px; padding: 4px 8px; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QCheckBox::indicator:checked { background: #49b75a; border: 1px solid #3b9e4b; }
QSlider::groove:horizontal {
    height: 4px;
    background: #d2d2d2;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #49b75a;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: white;
    border: 2px solid #49b75a;
    width: 13px;
    margin: -6px 0;
    border-radius: 7px;
}
QTabWidget::pane { background: #f4f4f4; border: 1px solid #d2d2d2; border-radius: 5px; }
QTabBar::tab { background: transparent; padding: 7px 4px; border: none; font-size: 11px; }
QTabBar::tab:selected { background: #49b75a; color: white; border-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 9px; background: #ededed; }
QScrollBar::handle:vertical { background: #bdbdbd; border-radius: 4px; min-height: 30px; }
QTextEdit {
    background: #171717;
    color: #efefef;
    border: 1px solid #c8c8c8;
    border-radius: 4px;
    font-family: Consolas;
    font-size: 11px;
}
QLabel#preview { background: #101010; border: 1px solid #c8c8c8; border-radius: 3px; }
QProgressBar { background: #ddd; border: 0; height: 7px; }
QProgressBar::chunk { background: #49b75a; }
QSplitter::handle { background: #d6d6d6; width: 2px; }
"""

# Backwards-compatible import name used by MainWindow.
DARK_QSS = LIGHT_QSS
