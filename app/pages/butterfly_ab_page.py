"""蝴蝶AB通道的独立工作区。"""

import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.widgets.folder_row import FolderRow
from engine import HIDDEN_SUBPROCESS
from app.widgets.log_panel import LogPanel


class ButterflyABPage(QWidget):
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, config):
        super().__init__()
        self.config = config
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(20)

        left = QFrame()
        left.setObjectName("sidebar")
        left.setMinimumWidth(440)
        left_layout = QVBoxLayout(left)

        files = QGroupBox("蝴蝶AB · 文件设置")
        form = QFormLayout(files)
        for label, key in (
            ("主视频 A 文件夹", "ab_main_folder"),
            ("辅助视频 B 文件夹", "ab_auxiliary_folder"),
            ("输出文件夹", "ab_output_folder"),
        ):
            row = FolderRow(initial=getattr(config, key))
            row.path_changed.connect(lambda value, name=key: setattr(config, name, value))
            form.addRow(label, row)
        left_layout.addWidget(files)

        actions = QGroupBox("批量处理")
        actions_layout = QVBoxLayout(actions)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("▶ 开始蝴蝶AB处理")
        self.start_button.setObjectName("accent")
        self.start_button.clicked.connect(self.start_requested)
        buttons.addWidget(self.start_button)
        self.stop_button = QPushButton("■ 停止处理")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        buttons.addWidget(self.stop_button)
        actions_layout.addLayout(buttons)

        self.delete_aux = QCheckBox("删除已用辅助视频 B")
        self.delete_aux.setChecked(config.ab_delete_used_aux)
        self.delete_aux.toggled.connect(
            lambda value: setattr(config, "ab_delete_used_aux", value)
        )
        self.repeat_count = QSpinBox()
        self.repeat_count.setRange(1, 100)
        self.repeat_count.setFixedWidth(64)
        self.repeat_count.setValue(config.ab_repeat_count)
        self.repeat_count.valueChanged.connect(
            lambda value: setattr(config, "ab_repeat_count", value)
        )
        self.progress = QProgressBar()
        self.progress.hide()
        actions_layout.addWidget(self.progress)
        left_layout.addWidget(actions)

        self.log = LogPanel("蝴蝶AB处理日志")
        clear = QPushButton("清空日志")
        clear.clicked.connect(self.log.clear)
        self.log.header_layout.addWidget(clear)
        left_layout.addWidget(self.log, 1)
        root.addWidget(left, 1)

        right = QFrame()
        right.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right)
        title = QLabel("蝴蝶AB 专用参数")
        title.setObjectName("brand")
        right_layout.addWidget(title)

        encoding = QGroupBox("输出与批量设置")
        encoding_grid = QGridLayout(encoding)
        encoding_grid.setHorizontalSpacing(16)
        encoding_grid.setVerticalSpacing(12)
        self.resolution = QComboBox()
        self.resolution.addItems(("720x1280", "1080x1920", "1080x2338"))
        self.resolution.setCurrentText(config.ab_resolution)
        self.resolution.setFixedWidth(180)
        self.resolution.currentTextChanged.connect(
            lambda value: setattr(config, "ab_resolution", value)
        )
        self.gpu = QCheckBox("启用 GPU 加速")
        self.gpu.setChecked(config.ab_gpu)
        self.gpu.toggled.connect(lambda value: setattr(config, "ab_gpu", value))
        encoding_grid.addWidget(QLabel("输出分辨率"), 0, 0)
        encoding_grid.addWidget(self.resolution, 0, 1)
        encoding_grid.addWidget(QLabel("编码器"), 0, 2)
        encoding_grid.addWidget(self.gpu, 0, 3)
        encoding_grid.addWidget(QLabel("每个 A 处理次数"), 1, 0)
        encoding_grid.addWidget(self.repeat_count, 1, 1)
        encoding_grid.addWidget(QLabel("素材清理"), 1, 2)
        encoding_grid.addWidget(self.delete_aux, 1, 3)
        encoding_grid.setColumnStretch(4, 1)
        right_layout.addWidget(encoding)

        preview_group = QGroupBox("当前处理预览")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_title = QLabel("等待开始处理")
        self.preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(self.preview_title)
        self.preview = QLabel("处理时将显示当前主视频 A")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(420, 520)
        preview_layout.addWidget(self.preview, 1)
        right_layout.addWidget(preview_group, 1)
        root.addWidget(right, 2)
        self._preview_pixmap = None

    def set_running(self, running):
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.progress.setVisible(running)
        if running:
            self.progress.setRange(0, 0)

    def show_task(self, task):
        video = Path(task["main"])
        self._show_video(video, f"正在处理：{video.name}")

    def show_first_video(self, folder):
        from engine.ffmpeg_builder import VIDEO_EXTS, list_media

        videos = list_media(str(folder), VIDEO_EXTS)
        if videos:
            self._show_video(videos[0], f"预览：{videos[0].name}")

    def _show_video(self, video, title):
        self.preview_title.setText(title)
        try:
            with tempfile.TemporaryDirectory() as folder:
                image = Path(folder) / "preview.png"
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", "0.5", "-i", str(video),
                        "-frames:v", "1", str(image),
                    ],
                    capture_output=True, timeout=15, check=True,
                    **HIDDEN_SUBPROCESS,
                )
                self._preview_pixmap = QPixmap(str(image))
                self._scale_preview()
        except Exception as error:
            self.preview.setText(f"预览生成失败：{error}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_preview()

    def _scale_preview(self):
        if self._preview_pixmap and not self._preview_pixmap.isNull():
            self.preview.setPixmap(
                self._preview_pixmap.scaled(
                    self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
