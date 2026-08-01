"""
BlackCat FlowCut — Deep Navy Blue Professional Theme
Design system: "Midnight Blue"
Deep navy palette with crisp sky-blue accents. Dark enough for
comfortable video editing, unmistakably blue in tone.
"""

MIDNIGHT_QSS = """
/* ══════════════════════════════════════════════════════════════
   FOUNDATION — Base layer, typography, global resets
   ══════════════════════════════════════════════════════════════ */

QWidget {
    background: #172640;
    color: #d4dff0;
    font-family: "Microsoft YaHei UI", "Segoe UI", system-ui;
    font-size: 12px;
}

QMainWindow {
    background: #111d32;
}

/* ── Panel cards (raised surfaces) ── */
QFrame#panel {
    background: #1b2c49;
    border: 1px solid #2c456d;
    border-radius: 10px;
}

/* ── Sidebar & navigation rail ── */
QFrame#sidebar {
    background: #192a46;
    border: 1px solid #2b4369;
    border-radius: 10px;
}

QFrame#channelBar {
    background: #070f1d;
    border: 1px solid #13213a;
    border-radius: 10px;
}

QFrame#rightPanel {
    background: #223858;
    border: 1px solid #42618e;
    border-radius: 10px;
}

QFrame#rightPanel QTabWidget::pane {
    background: #223858;
    border-color: #42618e;
}

QFrame#rightPanel QGroupBox,
QFrame#rightPanel QGroupBox::title {
    background: #294267;
    border-color: #4a6b99;
}

/* ══════════════════════════════════════════════════════════════
   TYPOGRAPHY — Brand, headings, labels
   ══════════════════════════════════════════════════════════════ */

QLabel {
    color: #c5d2e8;
    background: transparent;
}

QLabel#brand {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 2px;
}

QLabel#brandSub {
    color: #60a5fa;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}

QLabel#channelBrand {
    color: #ffffff;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 3px;
}

QLabel#status {
    color: #34d399;
    font-weight: 700;
    font-size: 11px;
    padding: 4px 14px;
    background: #0d2a1f;
    border: 1px solid #1a5a3e;
    border-radius: 12px;
}

QLabel#sectionTitle {
    color: #60a5fa;
    font-weight: 700;
    font-size: 10px;
    letter-spacing: 1.5px;
    padding: 2px 0;
}

QLabel#previewHint {
    color: #9a8550;
    font-size: 11px;
}

/* ══════════════════════════════════════════════════════════════
   GROUP BOX — Section containers with refined headers
   ══════════════════════════════════════════════════════════════ */

QGroupBox {
    background: #1b2c49;
    border: 1px solid #2c456d;
    border-radius: 10px;
    margin-top: 16px;
    padding: 18px 12px 12px;
    font-weight: 600;
    font-size: 12px;
    color: #d4dff0;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 2px 10px;
    color: #93bbf5;
    background: #1b2c49;
    border: 1px solid #2c456d;
    border-radius: 6px;
    font-size: 11px;
}

/* ══════════════════════════════════════════════════════════════
   INPUT FIELDS — Text, spin, combo, sliders
   ══════════════════════════════════════════════════════════════ */

QLineEdit, QSpinBox, QComboBox {
    background: #0b1324;
    color: #e4ebf6;
    border: 1px solid #1e3052;
    border-radius: 7px;
    padding: 6px 10px;
    min-height: 24px;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
}

QLineEdit:hover, QSpinBox:hover, QComboBox:hover {
    border-color: #2d4570;
    background: #0e172a;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    background: #0f1a30;
    border: 1px solid #3b82f6;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #1e3052;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    background: #131e36;
}

QComboBox::down-arrow {
    width: 8px;
    height: 8px;
}

QComboBox QAbstractItemView {
    background: #111d32;
    color: #d4dff0;
    border: 1px solid #1e3052;
    border-radius: 6px;
    outline: 0;
    selection-background-color: #1e3a64;
    selection-color: #ffffff;
    padding: 4px;
}

QComboBox QAbstractItemView::item {
    padding: 5px 10px;
    border-radius: 4px;
}

QComboBox QAbstractItemView::item:hover {
    background: #182a48;
}

/* ── SpinBox arrow buttons ── */
QSpinBox::up-button, QSpinBox::down-button {
    border: none;
    background: #1a2845;
    width: 18px;
    border-radius: 3px;
    margin: 2px;
}

QSpinBox::up-arrow {
    image: url(resources/spin-up.svg);
    width: 10px;
    height: 7px;
}

QSpinBox::down-arrow {
    image: url(resources/spin-down.svg);
    width: 10px;
    height: 7px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #243558;
}

/* ── Sliders ── */
QSlider::groove:horizontal {
    height: 5px;
    background: #0d172a;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #3b82f6, stop:1 #06b6d4
    );
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #60a5fa;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    border-color: #93bbf5;
    background: #eef4ff;
}

/* ── Checkboxes ── */
QCheckBox {
    color: #c5d2e8;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    background: #0b1324;
    border: 1px solid #284070;
    border-radius: 5px;
}

QCheckBox::indicator:hover {
    border-color: #3b82f6;
}

QCheckBox::indicator:checked {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #3b82f6, stop:1 #2563eb
    );
    border-color: #60a5fa;
    image: url(resources/check.svg);
}

/* ══════════════════════════════════════════════════════════════
   BUTTON SYSTEM — 5-tier hierarchy
   ══════════════════════════════════════════════════════════════ */

/* ── Tier 0: Default button ── */
QPushButton {
    background: #192844;
    color: #c5d2e8;
    border: 1px solid #243a5e;
    border-radius: 8px;
    padding: 7px 16px;
    min-height: 28px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton:hover {
    background: #1f3255;
    color: #e4ebf6;
    border-color: #345080;
}

QPushButton:pressed {
    background: #142038;
    padding-top: 8px;
    padding-bottom: 6px;
}

QPushButton:disabled {
    background: #111d30;
    color: #4a6088;
    border-color: #1a2845;
}

/* ── Tier 1: Primary / Accent button ── */
QPushButton#accent {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #3b82f6, stop:0.5 #2d74e8, stop:1 #06b6d4
    );
    color: #ffffff;
    border: 1px solid #60a5fa;
    border-radius: 8px;
    padding: 8px 20px;
    min-height: 30px;
    font-weight: 700;
    font-size: 13px;
}

QPushButton#accent:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #60a5fa, stop:0.5 #4d8cf5, stop:1 #22c8dd
    );
    border-color: #93bbf5;
}

QPushButton#accent:pressed {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #2563eb, stop:1 #0891b2
    );
    padding-top: 9px;
    padding-bottom: 7px;
}

/* ── Tier 2: Danger / Destructive button ── */
QPushButton#danger {
    background: #24161e;
    color: #f87171;
    border: 1px solid #4a2535;
    border-radius: 8px;
    padding: 7px 16px;
    min-height: 28px;
    font-weight: 600;
}

QPushButton#danger:hover {
    background: #311d28;
    color: #fca5a5;
    border-color: #6b2e44;
}

QPushButton#danger:pressed {
    background: #1a1016;
    padding-top: 8px;
    padding-bottom: 6px;
}

/* ── Tier 3: Ghost / Flat button ── */
QPushButton[flat="true"] {
    background: transparent;
    color: #7a95c0;
    border: none;
    border-radius: 6px;
    padding: 5px 12px;
    min-height: 26px;
    font-weight: 500;
}

QPushButton[flat="true"]:hover {
    background: #1c2b48;
    color: #c5d2e8;
}

QPushButton[flat="true"]:pressed {
    background: #152038;
    color: #e4ebf6;
}

/* ── Tier 4: Browse / compact button ── */
QPushButton#browse {
    min-width: 54px;
    padding: 5px 12px;
    font-size: 11px;
    border-radius: 6px;
    background: #192844;
    border: 1px solid #284070;
    color: #93bbf5;
    font-weight: 600;
}

QPushButton#browse:hover {
    background: #223558;
    color: #bdd6fb;
    border-color: #3b82f6;
}

/* ══════════════════════════════════════════════════════════════
   CHANNEL NAVIGATION — Persistent left rail buttons
   ══════════════════════════════════════════════════════════════ */

QPushButton#channelButton {
    background: #0f1b30;
    color: #7a95c0;
    border: 1px solid #172a48;
    border-radius: 8px;
    padding: 11px 12px;
    text-align: left;
    min-height: 28px;
    font-weight: 500;
    font-size: 12px;
}

QPushButton#channelButton:hover {
    color: #c5d2e8;
    background: #162440;
    border-color: #284070;
}

QPushButton#channelButton:disabled {
    color: #4a6088;
    background: #0b1526;
    border-color: #15243d;
}

QPushButton#channelButton:checked {
    color: #ffffff;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1e3a6e, stop:1 #1a3270
    );
    border: 1px solid #3b82f6;
    border-left: 3px solid #60a5fa;
    font-weight: 700;
}

/* ══════════════════════════════════════════════════════════════
   TABS — Right-side parameter tabs
   ══════════════════════════════════════════════════════════════ */

QTabWidget::pane {
    background: #192a46;
    border: 1px solid #2b456e;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    background: transparent;
    color: #5a7aa5;
    padding: 9px 6px 8px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 11px;
    font-weight: 600;
    margin: 0 1px;
}

QTabBar::tab:hover {
    color: #93bbf5;
}

QTabBar::tab:selected {
    color: #ffffff;
    background: #192c50;
    border-bottom: 2px solid #60a5fa;
    border-radius: 5px 5px 0 0;
}

/* ══════════════════════════════════════════════════════════════
   LOG & TERMINAL — Read-only text area
   ══════════════════════════════════════════════════════════════ */

QTextEdit {
    background: #070f1d;
    color: #6ee7b7;
    border: 1px solid #192c50;
    border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", "Fira Code", monospace;
    font-size: 11px;
    padding: 10px;
    selection-background-color: #1e3a64;
}

/* ── Log panel header ── */
QLabel#logHeader {
    color: #5a7aa5;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1px;
}

/* ══════════════════════════════════════════════════════════════
   PREVIEW CANVAS — Video preview frame
   ══════════════════════════════════════════════════════════════ */

QLabel#preview {
    background: #060e1c;
    border: 1px solid #192c50;
    border-radius: 8px;
}

/* ══════════════════════════════════════════════════════════════
   PROGRESS BAR — Slim modern progress indicator
   ══════════════════════════════════════════════════════════════ */

QProgressBar {
    background: #0b1426;
    color: #e4ebf6;
    border: 1px solid #1c2e4e;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    font-size: 9px;
    font-weight: 700;
}

QProgressBar::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #3b82f6, stop:1 #06b6d4
    );
    border-radius: 5px;
}

/* ══════════════════════════════════════════════════════════════
   CHROME — Scrollbars, splitters, tooltips
   ══════════════════════════════════════════════════════════════ */

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    width: 7px;
    background: #0b1526;
    border-radius: 4px;
    margin: 2px 0;
}

QScrollBar::handle:vertical {
    background: #284070;
    border-radius: 4px;
    min-height: 36px;
}

QScrollBar::handle:vertical:hover {
    background: #345590;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    height: 7px;
    background: #0b1526;
    border-radius: 4px;
    margin: 0 2px;
}

QScrollBar::handle:horizontal {
    background: #284070;
    border-radius: 4px;
    min-width: 36px;
}

QScrollBar::handle:horizontal:hover {
    background: #345590;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QSplitter::handle {
    background: #192c50;
    width: 2px;
}

QSplitter::handle:hover {
    background: #3b82f6;
}

QToolTip {
    background: #1a2b4a;
    color: #ffffff;
    border: 1px solid #3b82f6;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
}

/* ══════════════════════════════════════════════════════════════
   MISC — Menu, scroll area corner, etc.
   ══════════════════════════════════════════════════════════════ */

QMenu {
    background: #111d32;
    color: #d4dff0;
    border: 1px solid #1e3052;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    padding: 7px 28px 7px 14px;
    border-radius: 5px;
}

QMenu::item:selected {
    background: #1e3a64;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background: #1c2e4e;
    margin: 5px 10px;
}

QScrollArea QWidget {
    background: transparent;
}
"""

# Theme aliases
CERULEAN_QSS = MIDNIGHT_QSS
OBSIDIAN_QSS = MIDNIGHT_QSS
LIGHT_QSS = MIDNIGHT_QSS
