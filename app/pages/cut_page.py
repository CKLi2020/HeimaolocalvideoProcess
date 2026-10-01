"""视频裁剪通道：把长视频快速拆成固定时长的小视频。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.widgets.folder_row import FolderRow
from app.widgets.log_panel import LogPanel


class CutPage(QWidget):
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

        files = QGroupBox("视频裁剪")
        form = QFormLayout(files)
        self.main_folder = FolderRow(initial=config.cut_main_folder)
        self.main_folder.path_changed.connect(
            lambda value: setattr(config, "cut_main_folder", value)
        )
        form.addRow("长视频文件夹", self.main_folder)
        self.output_folder = FolderRow(initial=config.cut_output_folder)
        self.output_folder.path_changed.connect(
            lambda value: setattr(config, "cut_output_folder", value)
        )
        form.addRow("切片输出文件夹", self.output_folder)
        self.seconds = QSpinBox()
        self.seconds.setRange(1, 3600)
        self.seconds.setSuffix(" 秒")
        self.seconds.setValue(config.cut_segment_seconds)
        self.seconds.valueChanged.connect(
            lambda value: setattr(config, "cut_segment_seconds", value)
        )
        form.addRow("每段目标时长", self.seconds)
        settings_layout.addWidget(files)

        open_output = QPushButton("打开切片文件夹")
        open_output.clicked.connect(self._open_output)
        settings_layout.addWidget(open_output)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("▶ 开始批量裁剪")
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
        title = QLabel("长视频批量裁剪")
        title.setObjectName("brand")
        log_layout.addWidget(title)
        rule = QLabel(
            "主文件夹里的每个长视频都会拆成多个小视频。\n"
            "按原视频关键帧切割，不重复编码、画质不变。"
        )
        rule.setObjectName("sectionTitle")
        log_layout.addWidget(rule)
        self.current = QLabel("等待开始")
        log_layout.addWidget(self.current)
        self.log = LogPanel("裁剪日志")
        clear = QPushButton("清空日志")
        clear.clicked.connect(self.log.clear)
        self.log.header_layout.addWidget(clear)
        log_layout.addWidget(self.log, 1)
        root.addWidget(log_frame, 1)

    def _open_output(self) -> None:
        folder = Path(self.config.cut_output_folder)
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
        self.current.setText(f"正在裁剪：{Path(task['main']).name}")
