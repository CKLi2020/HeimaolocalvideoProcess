"""主窗口：组装所有标签页、预览区、日志区、操作按钮。"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
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
from app.pages.mover_page import MoverPage
from app.pages.template_page import TemplatePage
from app.pages.audio_page import AudioPage
from app.pages.opening_page import OpeningPage
from app.pages.face_color_page import FaceColorPage
from app.pages.butterfly_ab_page import ButterflyABPage
from app.pages.concat_page import ConcatPage
from app.pages.local_processor_page import LocalProcessorPage
from app.widgets.preview_canvas import PreviewCanvas
from app.widgets.log_panel import LogPanel
from app.widgets.param_row import ParamRow
from engine.worker import BatchWorker
from version import APP_NAME, APP_VERSION


def _format_expire_at(value: str) -> str:
    """把 ISO-8601 到期时间格式化为本地时间。

    当前本地运行模式不再有服务器到期时间，此函数保留给将来接入的授权模块
    （见 engine/auth.py），并由 tests/test_license_expiry_title.py 覆盖。
    """
    if not value:
        return "永久"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


class MainWindow(QMainWindow):
    log_received = Signal(str)
    progress_received = Signal(int, int)
    work_done = Signal(bool, str)
    task_received = Signal(object)

    def __init__(self, config: AppConfig, root_dir: Path):
        super().__init__()
        self.config = config
        self.root_dir = root_dir
        self.setWindowTitle(f"{APP_NAME} V{APP_VERSION}")
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
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        header_layout.addWidget(brand)
        brand_sub = QLabel("BLACKCAT")
        brand_sub.setObjectName("brandSub")
        header_layout.addWidget(brand_sub)
        header_layout.addStretch()
        self._status_label = QLabel("● 视频处理")
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
        channel_brand = QLabel(APP_NAME)
        channel_brand.setObjectName("channelBrand")
        channel_brand.setAlignment(Qt.AlignCenter)
        channel_layout.addWidget(channel_brand)
        channel_caption = QLabel("BLACKCAT")
        channel_caption.setObjectName("brandSub")
        channel_caption.setAlignment(Qt.AlignCenter)
        channel_layout.addWidget(channel_caption)
        channel_layout.addSpacing(18)
        channel_layout.addWidget(QLabel("选择通道"))

        self._active_channel = "local_processor"
        self._channel_group = QButtonGroup(self)
        self._channel_group.setExclusive(True)
        channels = (
            ("视频处理", "local_processor"),
            ("蒙版模式", "hdh"),
            ("素材拼接", "concat"),
            ("蝴蝶AB", "butterfly_ab"),
        )
        # 「蝴蝶AB」按钮收起。只藏按钮，通道本身一点没动：_select_channel、
        # _workspace_stack 里的蝴蝶页、_on_start 的蝴蝶分支都还在原位，只是界面
        # 上没有入口能切过去。要把按钮放回来，
        # 只需把 "butterfly_ab" 从这个集合里删掉。
        hidden_channels = {"butterfly_ab"}
        for name, channel in channels:
            button = QPushButton(name)
            button.setObjectName("channelButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, value=channel: self._select_channel(value)
            )
            self._channel_group.addButton(button)
            channel_layout.addWidget(button)
            if channel in hidden_channels:
                button.setVisible(False)
            if channel == "local_processor":
                button.setChecked(True)
        channel_layout.addStretch()
        machine_title = QLabel("本机信息")
        machine_title.setObjectName("machineTitle")
        channel_layout.addWidget(machine_title)
        self._machine_gpu = QLabel("●  正在检测…")
        self._machine_gpu.setObjectName("machineInfo")
        self._machine_gpu.setWordWrap(True)
        channel_layout.addWidget(self._machine_gpu)
        channel_layout.addSpacing(8)
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
        # 「删除已用辅助视频」整项去掉（用户要求）：这个开关会把整批用完的输入
        # 文件直接 unlink，撤不回来 —— 模板模式下更危险，背景槽被模板占着，
        # 一开就删光模板库（engine/pipeline.py 里那段守卫就是为它加的）。
        # 能力仍在 engine/pipeline.py，靠 config.delete_used_aux 读；界面上不再
        # 留入口，config.json 与预设里的值继续原样往返。
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
        hint = QLabel("⚠ 请选择有效的主视频和背景素材")
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
        mover_page = MoverPage(self.config)
        mover_page.preview_changed.connect(self._preview_refresh)
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
            "移动贴纸": mover_page,
            "封面": OpeningPage(self.config, "cover"),
            "字幕设置": OpeningPage(self.config, "subtitle"),
            "画面滤镜": FaceColorPage(self.config, "color"),
            "人脸遮挡": FaceColorPage(self.config, "face"),
            "卡秒": FaceColorPage(self.config, "mp4"),
            "模板": TemplatePage(self.config, self.root_dir),
            "声音处理": AudioPage(self.config, self.root_dir),
        }
        # 「贴图」页整页收起（贴纸/扫光 与 画中画 都不再露出）。
        # 必须留住这个引用：里面的子页仍挂在 self._pages 上参与参数联动与
        # 配置读写，picture_page 一旦被回收，Qt 会连子控件一起销毁。
        self._hidden_picture_page = picture_page

        # 「人脸遮挡」页也收起：它仍留在 self._pages 里（不建标签页即可），
        # 所以人脸那几行参数继续参与联动与配置回写，config.json 与预设里的
        # face_blur_* 不会因为页面消失而被静默丢掉。要重新露出只需把下面这行
        # 加回 tabs 元组。
        tabs = (
            ("基础参数", self._pages["基础参数"]),
            ("封面", self._pages["封面"]),
            ("模板", self._pages["模板"]),
            ("声音处理", self._pages["声音处理"]),
            ("移动贴纸", self._pages["移动贴纸"]),
            ("画面滤镜", self._pages["画面滤镜"]),
            ("蒙版", self._pages["蒙版"]),
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
        self._concat_page = ConcatPage(self.config, self.root_dir)
        self._concat_page.start_requested.connect(self._on_start)
        self._concat_page.stop_requested.connect(self._on_stop)
        self._local_processor_page = LocalProcessorPage(self.root_dir)
        profile = self._local_processor_page.service.gpu_profile
        gpu_name = profile.get("gpu_name")
        if profile.get("available"):
            machine_text, machine_color = f"●  {gpu_name}\n支持 GPU 加速", "#34d399"
        elif gpu_name:
            machine_text, machine_color = f"●  {gpu_name}\n不支持 GPU 加速", "#fbbf24"
        else:
            machine_text, machine_color = "●  未检测到支持的显卡", "#f87171"
        self._machine_gpu.setText(machine_text)
        self._machine_gpu.setStyleSheet(f"color: {machine_color};")
        self._workspace_stack = QStackedWidget()
        self._workspace_stack.addWidget(hdh_workspace)
        self._workspace_stack.addWidget(self._butterfly_page)
        self._workspace_stack.addWidget(self._concat_page)
        self._workspace_stack.addWidget(self._local_processor_page)
        splitter.addWidget(self._workspace_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 1510])
        root_layout.addWidget(splitter, stretch=1)
        self._select_channel("local_processor")

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
        self._workspace_stack.setCurrentIndex(
            {"hdh": 0, "butterfly_ab": 1, "concat": 2, "local_processor": 3}[channel]
        )
        if channel == "butterfly_ab":
            self._butterfly_page.show_first_video(
                self._resolve(self.config.ab_main_folder)
            )
        status = {
            "hdh": "● 蒙版模式",
            "butterfly_ab": "● 蝴蝶AB通道",
            "concat": "● 素材拼接",
            "local_processor": "● 视频处理",
        }[channel]
        self._set_status(
            status,
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
        if self._active_channel == "local_processor":
            self._local_processor_page.start()
            return
        if self._active_channel == "butterfly_ab":
            self._on_start_butterfly()
            return
        if self._active_channel == "concat":
            self._on_start_concat()
            return

        # 基本校验。辅助视频不再是必填项：界面上已经没有它的入口，
        # 缺素材时引擎用纯色画布兜底（见 engine/ffmpeg_builder.py 的
        # background_video is None 分支），这里再拦就没人解得开了。
        if not self.config.main_folder or not self.config.output_folder:
            QMessageBox.warning(self, "提示", "请先设置主素材和输出文件夹。")
            return

        main_dir = self._resolve(self.config.main_folder)
        if not main_dir.is_dir():
            QMessageBox.warning(self, "提示", "主素材文件夹不存在。")
            return

        self._save_config()
        self._log.clear()
        self._set_status("● 正在处理", "#fbbf24", "#1f1a0e", "#4a3a15")
        self._progress.setRange(0, 0)
        self._progress.show()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._running_channel = "hdh"
        self._worker.start(
            self.config, self.root_dir, self._active_channel,
        )

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
        self._worker.start(
            self.config, self.root_dir, "butterfly_ab",
        )

    def _on_start_concat(self) -> None:
        main_folder = self._resolve(self.config.concat_main_folder)
        if not main_folder.is_dir():
            QMessageBox.warning(self, "提示", "请选择有效的主素材文件夹。")
            return
        if not self.config.concat_prepend and not self.config.concat_append:
            QMessageBox.warning(self, "提示", "请至少选择一个拼接位置。")
            return
        for enabled, value, name in (
            (self.config.concat_prepend, self.config.concat_head_file, "头部"),
            (self.config.concat_append, self.config.concat_tail_file, "尾部"),
        ):
            if enabled and not self._resolve(value).is_file():
                QMessageBox.warning(self, "提示", f"请选择有效的{name}素材文件。")
                return
        self._save_config()
        self._running_channel = "concat"
        self._concat_page.log.clear()
        self._concat_page.set_running(True)
        self._set_status("● 素材拼接中", "#fbbf24", "#1f1a0e", "#4a3a15")
        self._worker.start(self.config, self.root_dir, "concat")

    def _on_stop(self) -> None:
        """停止处理。"""
        if self._active_channel == "local_processor":
            self._local_processor_page.stop()
            return
        self._worker.cancel()
        running = getattr(self, "_running_channel", "hdh")
        if running == "butterfly_ab":
            self._butterfly_page.stop_button.setEnabled(False)
        elif running == "concat":
            self._concat_page.stop_button.setEnabled(False)
        else:
            self._btn_stop.setEnabled(False)

    def closeEvent(self, event) -> None:
        """关闭窗口时一并终止两类后台任务。"""
        self._worker.cancel()
        self._local_processor_page.stop()
        event.accept()

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
        running = getattr(self, "_running_channel", "hdh")
        if running == "butterfly_ab":
            self._butterfly_page.log.append(text)
        elif running == "concat":
            self._concat_page.log.append(text)
        else:
            self._log.append(text)

    def _on_progress(self, current: int, total: int) -> None:
        running = getattr(self, "_running_channel", "hdh")
        progress = {
            "butterfly_ab": self._butterfly_page.progress,
            "concat": self._concat_page.progress,
        }.get(running, self._progress)
        progress.setRange(0, total)
        progress.setValue(current)

    def _on_task(self, task: dict) -> None:
        running = getattr(self, "_running_channel", "hdh")
        if running == "butterfly_ab":
            self._butterfly_page.show_task(task)
            return
        if running == "concat":
            self._concat_page.show_task(task)
            return
        self._preview_title.setText(f"● 正在处理：{Path(task['main']).name}")
        self._preview.show_task(task)

    def _on_done(self, success: bool, message: str) -> None:
        running = getattr(self, "_running_channel", "hdh")
        butterfly = running == "butterfly_ab"
        concat = running == "concat"
        if butterfly:
            self._butterfly_page.set_running(False)
        elif concat:
            self._concat_page.set_running(False)
        else:
            self._progress.hide()
            self._btn_start.setEnabled(True)
            self._btn_stop.setEnabled(False)
        if success:
            status = "● 素材拼接" if concat else (
                "● 蝴蝶AB通道" if butterfly else "● 蒙版模式"
            )
            self._set_status(
                status,
                "#34d399", "#0d2a1f", "#1a5a3e",
            )
        else:
            self._set_status("● " + message, "#f87171", "#1f1518", "#3d1f28")
        target_log = self._concat_page.log if concat else (
            self._butterfly_page.log if butterfly else self._log
        )
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
        # 按标签名找，不写索引：右栏的页会增减（「贴图」「人脸遮挡」已收起），
        # 写死索引会静默指到别的页上。
        # 表里只留右栏真有标签页的模式；对不上的模式走 .get 的兜底（基础参数），
        # 不会像以前那样指到一个已经不在标签栏里的名字上、找一圈什么都不做。
        mode_to_tab = {
            "鹤漫剪辑": "基础参数",
            "语音识别": "画面滤镜",
        }
        name = mode_to_tab.get(mode, "基础参数")
        for idx in range(self._tabs.count()):
            if self._tabs.tabText(idx) == name:
                self._tabs.setCurrentIndex(idx)
                return

    def _save_config(self) -> None:
        """回写配置到 config.json。"""
        config_path = self.root_dir / "config.json"
        self.config.to_json(config_path)
