"""主窗口：组装所有标签页、预览区、日志区、操作按钮。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon

from config import AppConfig
from app.theme import MIDNIGHT_QSS
from app.pages.files_page import FilesPage
from app.pages.canvas_page import CanvasPage
from app.pages.mask_page import MaskPage
from app.pages.pip_page import PipPage
from app.pages.sticker_page import StickerPage
from app.pages.opening_page import OpeningPage
from app.pages.face_color_page import FaceColorPage
from app.pages.butterfly_ab_page import ButterflyABPage
from app.widgets.preview_canvas import PreviewCanvas
from app.widgets.log_panel import LogPanel
from app.widgets.param_row import ParamRow
from engine.worker import BatchWorker


class MainWindow(QMainWindow):
    log_received = Signal(str)
    progress_received = Signal(int, int)
    work_done = Signal(bool, str)
    task_received = Signal(object)

    def __init__(self, config: AppConfig, root_dir: Path):
        super().__init__()
        self.config = config
        self.root_dir = root_dir
        self.setWindowTitle("黑猫苍老师")
        self.setGeometry(80, 50, 1500, 900)
        self.setMinimumSize(1280, 720)
        self.setStyleSheet(MIDNIGHT_QSS)

        self.log_received.connect(self._on_log)
        self.progress_received.connect(self._on_progress)
        self.work_done.connect(self._on_done)
        self.task_received.connect(self._on_task)
        self._worker = BatchWorker(
            log_callback=self.log_received.emit,
            progress_callback=self.progress_received.emit,
            done_callback=self.work_done.emit,
            task_callback=self.task_received.emit,
        )

        self._setup_ui()
        self._preview.schedule_refresh()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(6, 5, 6, 5)
        root_layout.setSpacing(6)

        header = QFrame()
        header.setObjectName("panel")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 3, 8, 3)
        brand = QLabel("黑猫苍老师")
        brand.setObjectName("brand")
        header_layout.addWidget(brand)
        brand_sub = QLabel("BLACKCAT")
        brand_sub.setObjectName("brandSub")
        header_layout.addWidget(brand_sub)
        header_layout.addStretch()
        self._status_label = QLabel("● 蒙版通道")
        self._status_label.setObjectName("status")
        header_layout.addWidget(self._status_label)
        root_layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(20)

        # Persistent channel navigation. Every channel routes to a real page.
        channel_panel = QFrame()
        channel_panel.setObjectName("channelBar")
        channel_panel.setMinimumWidth(170)
        channel_panel.setMaximumWidth(190)
        channel_layout = QVBoxLayout(channel_panel)
        channel_layout.setContentsMargins(12, 18, 12, 12)
        channel_layout.setSpacing(9)
        channel_logo = QLabel()
        channel_logo.setPixmap(QIcon(str(self.root_dir / "ico" / "feng_logo.ico")).pixmap(120, 120))
        channel_logo.setAlignment(Qt.AlignCenter)
        channel_layout.addWidget(channel_logo)
        channel_brand = QLabel("黑猫苍老师")
        channel_brand.setObjectName("channelBrand")
        channel_brand.setAlignment(Qt.AlignCenter)
        channel_layout.addWidget(channel_brand)
        channel_caption = QLabel("BLACKCAT")
        channel_caption.setObjectName("brandSub")
        channel_caption.setAlignment(Qt.AlignCenter)
        channel_layout.addWidget(channel_caption)
        channel_layout.addSpacing(18)
        channel_layout.addWidget(QLabel("选择通道"))

        self._active_channel = "hdh"
        self._channel_group = QButtonGroup(self)
        self._channel_group.setExclusive(True)
        channels = (
            ("01", "蒙版通道", "hdh"),
            ("02", "蝴蝶AB", "butterfly_ab"),
            ("03", "最新连怼（Coming）", "coming"),
        )
        for number, name, channel in channels:
            button = QPushButton(f"{number}   {name}")
            button.setObjectName("channelButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, value=channel: self._select_channel(value)
            )
            self._channel_group.addButton(button)
            channel_layout.addWidget(button)
            button.setEnabled(channel != "coming")
            if channel == "hdh":
                button.setChecked(True)
        channel_layout.addStretch()
        channel_footer = QLabel("BLACK CAT VIDEO")
        channel_footer.setObjectName("brandSub")
        channel_layout.addWidget(channel_footer)
        splitter.addWidget(channel_panel)

        hdh_workspace = QSplitter(Qt.Horizontal)
        hdh_workspace.setHandleWidth(20)

        # Left: folders, controls, presets and log.
        left_panel = QFrame()
        left_panel.setObjectName("sidebar")
        left_panel.setMinimumWidth(330)
        left_panel.setMaximumWidth(350)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 4, 5, 5)
        left_layout.setSpacing(8)
        self._files_page = FilesPage(self.config)
        self._files_page.setMinimumHeight(300)
        left_layout.addWidget(self._files_page)

        controls = QFrame()
        controls.setObjectName("panel")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(7, 6, 7, 6)
        controls_layout.setSpacing(5)
        row = QHBoxLayout()
        self._btn_start = QPushButton("▶ 开始处理")
        self._btn_start.setObjectName("accent")
        self._btn_start.clicked.connect(self._on_start)
        row.addWidget(self._btn_start)
        self._btn_stop = QPushButton("■ 停止处理")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_stop.setEnabled(False)
        row.addWidget(self._btn_stop)
        clear_log = QPushButton("清空日志")
        clear_log.clicked.connect(self._log_clear)
        controls_layout.addLayout(row)

        batch_row = QHBoxLayout()
        self._delete_aux = QCheckBox("删除已用辅助视频")
        self._delete_aux.setChecked(self.config.delete_used_aux)
        self._delete_aux.toggled.connect(
            lambda value: setattr(self.config, "delete_used_aux", value)
        )
        batch_row.addWidget(self._delete_aux)
        batch_row.addStretch()
        batch_row.addWidget(QLabel("裂变："))
        self._repeat_count = QSpinBox()
        self._repeat_count.setRange(1, 100)
        self._repeat_count.setValue(self.config.repeat_count)
        self._repeat_count.valueChanged.connect(
            lambda value: setattr(self.config, "repeat_count", value)
        )
        batch_row.addWidget(self._repeat_count)
        controls_layout.addLayout(batch_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self._progress.hide()
        controls_layout.addWidget(self._progress)
        left_layout.addWidget(controls)
        self._log = LogPanel("处理日志")
        self._log.header_layout.addWidget(clear_log)
        left_layout.addWidget(self._log, 1)
        hdh_workspace.addWidget(left_panel)

        # Center: large preview canvas.
        center_panel = QFrame()
        center_panel.setObjectName("panel")
        center_panel.setMinimumWidth(440)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(7, 5, 7, 7)
        preview_bar = QHBoxLayout()
        self._preview_title = QLabel("● 可视化预览（与导出参数同步）")
        self._preview_title.setObjectName("sectionTitle")
        self._preview_title.setStyleSheet("font-size: 11px;")
        preview_bar.addWidget(self._preview_title)
        preview_bar.addStretch()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._preview_refresh)
        preview_bar.addWidget(refresh)
        center_layout.addLayout(preview_bar)
        self._preview = PreviewCanvas(self.config, self.root_dir)
        self._files_page.paths_changed.connect(self._preview.schedule_refresh)
        self._files_page.paths_changed.connect(lambda: self._save_config())
        center_layout.addWidget(self._preview, 1)
        hint = QLabel("⚠ 请选择有效的主视频和辅助视频文件夹")
        hint.setAlignment(Qt.AlignCenter)
        hint.setObjectName("previewHint")
        center_layout.addWidget(hint)
        hdh_workspace.addWidget(center_panel)

        # Right: reference-style compact parameter tabs.
        right_panel = QFrame()
        right_panel.setObjectName("rightPanel")
        right_panel.setMinimumWidth(340)
        right_panel.setMaximumWidth(360)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        self._tabs = QTabWidget()
        self._tabs.tabBar().setExpanding(True)
        self._tabs.tabBar().setUsesScrollButtons(False)
        pip_page = PipPage(self.config)
        sticker_page = StickerPage(self.config)
        sticker_page.preview_changed.connect(self._preview_refresh)
        picture_page = QWidget()
        picture_layout = QVBoxLayout(picture_page)
        picture_layout.setContentsMargins(0, 0, 0, 0)
        picture_tabs = QTabWidget()
        picture_tabs.addTab(sticker_page, "贴纸/扫光")
        picture_tabs.addTab(pip_page, "画中画")
        picture_layout.addWidget(picture_tabs)

        self._pages = {
            "文件与批量": self._files_page,
            "基础参数": CanvasPage(self.config),
            "蒙版": MaskPage(self.config),
            "画中画": pip_page,
            "贴纸": sticker_page,
            "封面": OpeningPage(self.config, "cover"),
            "字幕设置": OpeningPage(self.config, "subtitle"),
            "画面滤镜": FaceColorPage(self.config, "color"),
            "人脸遮挡": FaceColorPage(self.config, "face"),
            "卡秒": FaceColorPage(self.config, "mp4"),
        }
        tabs = (
            ("基础参数", self._pages["基础参数"]),
            ("蒙版", self._pages["蒙版"]),
            ("贴图", picture_page),
            ("封面", self._pages["封面"]),
            ("画面滤镜", self._pages["画面滤镜"]),
            ("人脸遮挡", self._pages["人脸遮挡"]),
        )
        for name, page in tabs:
            self._tabs.addTab(page, name)
        right_layout.addWidget(self._tabs, stretch=1)
        # ── Wire every parameter row across all pages to live preview ──
        self._wire_params_to_preview()
        hdh_workspace.addWidget(right_panel)
        hdh_workspace.setStretchFactor(0, 0)
        hdh_workspace.setStretchFactor(1, 1)
        hdh_workspace.setStretchFactor(2, 0)
        hdh_workspace.setSizes([340, 850, 350])

        self._butterfly_page = ButterflyABPage(self.config)
        self._butterfly_page.start_requested.connect(self._on_start)
        self._butterfly_page.stop_requested.connect(self._on_stop)
        self._workspace_stack = QStackedWidget()
        self._workspace_stack.addWidget(hdh_workspace)
        self._workspace_stack.addWidget(self._butterfly_page)
        splitter.addWidget(self._workspace_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 1510])
        root_layout.addWidget(splitter, stretch=1)

    def _preview_refresh(self) -> None:
        self._preview.schedule_refresh()

    def _wire_params_to_preview(self) -> None:
        """Connect every parameter row across all pages to live preview refresh."""
        for page in self._pages.values():
            for row in getattr(page, "_rows", {}).values():
                if hasattr(row, "value_changed"):
                    row.value_changed.connect(self._preview.schedule_refresh)
                if hasattr(row, "path_changed"):
                    row.path_changed.connect(self._preview.schedule_refresh)

    def _select_channel(self, channel: str) -> None:
        self._active_channel = channel
        self._workspace_stack.setCurrentIndex(1 if channel == "butterfly_ab" else 0)
        if channel == "butterfly_ab":
            self._butterfly_page.show_first_video(
                self._resolve(self.config.ab_main_folder)
            )
        self._set_status(
            "● 蝴蝶AB通道" if channel == "butterfly_ab" else "● 蒙版通道",
            "#34d399", "#0d2a1f", "#1a5a3e",
        )

    def _log_clear(self) -> None:
        if hasattr(self, "_log"):
            self._log.clear()

    # ═══════════════════════════════════════
    # 操作回调
    # ═══════════════════════════════════════

    def _on_start(self) -> None:
        """开始批量处理。"""
        if self._active_channel == "butterfly_ab":
            self._on_start_butterfly()
            return

        # 基本校验
        if not self.config.main_folder or not self.config.background_folder or not self.config.output_folder:
            QMessageBox.warning(self, "提示", "请先设置主素材、辅助视频和输出文件夹。")
            return

        main_dir = self._resolve(self.config.main_folder)
        bg_dir = self._resolve(self.config.background_folder)
        if not main_dir.is_dir():
            QMessageBox.warning(self, "提示", "主素材文件夹不存在。")
            return
        if not bg_dir.is_dir():
            QMessageBox.warning(self, "提示", "辅助视频文件夹不存在。")
            return

        self._save_config()
        self._log.clear()
        self._set_status("● 正在处理", "#fbbf24", "#1f1a0e", "#4a3a15")
        self._progress.setRange(0, 0)
        self._progress.show()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._running_channel = "hdh"
        self._worker.start(self.config, self.root_dir, self._active_channel)

    def _on_start_butterfly(self) -> None:
        for value, message in (
            (self.config.ab_main_folder, "请设置主视频 A 文件夹。"),
            (self.config.ab_auxiliary_folder, "请设置辅助视频 B 文件夹。"),
            (self.config.ab_output_folder, "请设置输出文件夹。"),
        ):
            if not value:
                QMessageBox.warning(self, "提示", message)
                return
        if not self._resolve(self.config.ab_main_folder).is_dir():
            QMessageBox.warning(self, "提示", "主视频 A 文件夹不存在。")
            return
        if not self._resolve(self.config.ab_auxiliary_folder).is_dir():
            QMessageBox.warning(self, "提示", "辅助视频 B 文件夹不存在。")
            return

        self._save_config()
        self._running_channel = "butterfly_ab"
        self._butterfly_page.log.clear()
        self._butterfly_page.set_running(True)
        self._set_status("● 蝴蝶AB处理中", "#fbbf24", "#1f1a0e", "#4a3a15")
        self._worker.start(self.config, self.root_dir, "butterfly_ab")

    def _on_stop(self) -> None:
        """停止处理。"""
        self._worker.cancel()
        if getattr(self, "_running_channel", "hdh") == "butterfly_ab":
            self._butterfly_page.stop_button.setEnabled(False)
        else:
            self._btn_stop.setEnabled(False)

    def _on_self_test(self) -> None:
        """环境自检。"""
        self._log.clear()
        self._log.append("═══ 环境自检 ═══", "#60a5fa")
        self._set_status("● 自检中", "#93c3fd", "#111c30", "#1e3a6e")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(False)
        self._worker.start_self_test(self.root_dir)

    def _on_open_output(self) -> None:
        """打开成品目录。"""
        self._save_config()
        output = self._resolve(self.config.output_folder)
        output.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(output.resolve())])

    # ═══════════════════════════════════════
    # Worker 回调
    # ═══════════════════════════════════════

    def _on_log(self, text: str) -> None:
        if getattr(self, "_running_channel", "hdh") == "butterfly_ab":
            self._butterfly_page.log.append(text)
        else:
            self._log.append(text)

    def _on_progress(self, current: int, total: int) -> None:
        progress = (
            self._butterfly_page.progress
            if getattr(self, "_running_channel", "hdh") == "butterfly_ab"
            else self._progress
        )
        progress.setRange(0, total)
        progress.setValue(current)

    def _on_task(self, task: dict) -> None:
        if getattr(self, "_running_channel", "hdh") == "butterfly_ab":
            self._butterfly_page.show_task(task)
            return
        self._preview_title.setText(f"● 正在处理：{Path(task['main']).name}")
        self._preview.show_task(task)

    def _on_done(self, success: bool, message: str) -> None:
        butterfly = getattr(self, "_running_channel", "hdh") == "butterfly_ab"
        if butterfly:
            self._butterfly_page.set_running(False)
        else:
            self._progress.hide()
            self._btn_start.setEnabled(True)
            self._btn_stop.setEnabled(False)
        if success:
            self._set_status(
                "● 蝴蝶AB通道" if butterfly else "● 蒙版通道",
                "#34d399", "#0d2a1f", "#1a5a3e",
            )
        else:
            self._set_status("● " + message, "#f87171", "#1f1518", "#3d1f28")
        target_log = self._butterfly_page.log if butterfly else self._log
        target_log.append("--- " + message + " ---", "#5a7aa5")

    # ═══════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════

    def _set_status(self, text: str, color: str, bg: str = "#0d2a1f", border: str = "#1a5a3e") -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"font-size: 11px; padding: 5px 14px;"
            f"background: {bg}; border: 1px solid {border};"
            f"border-radius: 12px; color: {color}; font-weight: 700;"
        )

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root_dir / path

    def _switch_mode(self, mode: str) -> None:
        """切换编辑模式标签页。"""
        mode_to_tab = {
            "鹤漫剪辑": 0,
            "语音识别": 4,
            "人脸处理": 5,
            "MP4工具": 5,
        }
        idx = mode_to_tab.get(mode, 0)
        self._tabs.setCurrentIndex(idx)

    def _save_config(self) -> None:
        """回写配置到 config.json。"""
        config_path = self.root_dir / "config.json"
        self.config.to_json(config_path)
