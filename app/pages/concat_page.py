"""素材拼接通道界面。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.widgets.folder_row import FolderRow
from app.widgets.log_panel import LogPanel


class FileRow(QWidget):
    path_changed = Signal(str)

    def __init__(self, initial: str = "", kind: str = "素材"):
        super().__init__()
        self.kind = kind
        self.setMinimumHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit(initial)
        self.edit.setPlaceholderText(f"选择一个{kind}视频...")
        self.edit.textChanged.connect(self.path_changed)
        layout.addWidget(self.edit, 1)
        button = QPushButton("选择")
        button.setObjectName("browse")
        button.setFixedWidth(64)
        button.clicked.connect(self._browse)
        layout.addWidget(button)

    def _browse(self) -> None:
        from engine.ffmpeg_builder import VIDEO_EXTS

        patterns = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择{self.kind}素材", self.edit.text(),
            f"视频 ({patterns});;所有文件 (*)",
        )
        if path:
            self.edit.setText(path)


class ConcatPage(QWidget):
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, config, root_dir: Path):
        super().__init__()
        self.config = config
        self.root_dir = root_dir
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(20)

        settings = QFrame()
        settings.setObjectName("sidebar")
        settings.setMinimumWidth(470)
        settings.setMaximumWidth(540)
        settings_layout = QVBoxLayout(settings)

        files = QGroupBox("素材拼接")
        form = QFormLayout(files)
        self.main_folder = FolderRow(initial=config.concat_main_folder)
        self.main_folder.path_changed.connect(
            lambda value: setattr(config, "concat_main_folder", value)
        )
        form.addRow("主素材文件夹", self.main_folder)
        self.head = FileRow(config.concat_head_file, "头部")
        self.head.path_changed.connect(
            lambda value: setattr(config, "concat_head_file", value)
        )
        form.addRow("头部素材文件", self.head)
        self.tail = FileRow(config.concat_tail_file, "尾部")
        self.tail.path_changed.connect(
            lambda value: setattr(config, "concat_tail_file", value)
        )
        form.addRow("尾部素材文件", self.tail)

        position = QWidget()
        position_layout = QHBoxLayout(position)
        position_layout.setContentsMargins(0, 0, 0, 0)
        self.before = QCheckBox("拼到前面")
        self.after = QCheckBox("拼到后面")
        self.before.setChecked(config.concat_prepend)
        self.after.setChecked(config.concat_append)
        self.before.toggled.connect(self._prepend_changed)
        self.after.toggled.connect(self._append_changed)
        position_layout.addWidget(self.before)
        position_layout.addWidget(self.after)
        form.addRow("拼接位置", position)
        self._sync_file_rows()
        settings_layout.addWidget(files)

        output = QGroupBox("输出")
        output_layout = QVBoxLayout(output)
        self.output_label = QLabel(f"成品保存到：{config.concat_output_folder}")
        self.output_label.setWordWrap(True)
        output_layout.addWidget(self.output_label)
        open_output = QPushButton("打开成品文件夹")
        open_output.clicked.connect(self._open_output)
        output_layout.addWidget(open_output)
        settings_layout.addWidget(output)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("▶ 开始批量拼接")
        self.start_button.setObjectName("accent")
        self.start_button.clicked.connect(self.start_requested)
        buttons.addWidget(self.start_button)
        self.stop_button = QPushButton("■ 停止")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        buttons.addWidget(self.stop_button)
        settings_layout.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.hide()
        settings_layout.addWidget(self.progress)
        settings_layout.addStretch()
        root.addWidget(settings)

        log_frame = QFrame()
        log_frame.setObjectName("rightPanel")
        log_layout = QVBoxLayout(log_frame)
        title = QLabel("素材批量拼接")
        title.setObjectName("brand")
        log_layout.addWidget(title)
        rule = QLabel(
            "主素材文件夹里的每个视频，都会按勾选结果拼接头部、尾部素材。\n"
            "例如文件夹有 10 个视频，就会生成 10 个拼接成品。"
        )
        rule.setObjectName("sectionTitle")
        log_layout.addWidget(rule)
        self.current = QLabel("等待开始")
        log_layout.addWidget(self.current)
        self.log = LogPanel("拼接日志")
        clear = QPushButton("清空日志")
        clear.clicked.connect(self.log.clear)
        self.log.header_layout.addWidget(clear)
        log_layout.addWidget(self.log, 1)
        root.addWidget(log_frame, 1)

    def _prepend_changed(self, checked: bool) -> None:
        self.config.concat_prepend = checked
        self._sync_file_rows()

    def _append_changed(self, checked: bool) -> None:
        self.config.concat_append = checked
        self._sync_file_rows()

    def _sync_file_rows(self) -> None:
        self.head.setEnabled(self.before.isChecked())
        self.tail.setEnabled(self.after.isChecked())

    def _open_output(self) -> None:
        folder = Path(self.config.concat_output_folder)
        if not folder.is_absolute():
            folder = self.root_dir / folder
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder.resolve())])

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.progress.setVisible(running)
        if running:
            self.progress.setRange(0, 0)

    def show_task(self, task: dict) -> None:
        positions = " + ".join(task["positions"])
        self.current.setText(
            f"正在拼接：{Path(task['main']).name}  |  {positions}"
        )
