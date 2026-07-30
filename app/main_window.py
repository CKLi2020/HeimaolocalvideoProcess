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
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)
from PySide6.QtCore import Qt, QTimer, Signal

from config import AppConfig
from app.theme import DARK_QSS
from app.pages.files_page import FilesPage
from app.pages.canvas_page import CanvasPage
from app.pages.mask_page import MaskPage
from app.pages.pip_page import PipPage
from app.pages.sticker_page import StickerPage
from app.pages.opening_page import OpeningPage
from app.pages.face_color_page import FaceColorPage
from app.widgets.preview_canvas import PreviewCanvas
from app.widgets.log_panel import LogPanel
from app.preset_manager import PresetManager
from engine.worker import BatchWorker


class MainWindow(QMainWindow):
    log_received = Signal(str)
    progress_received = Signal(int, int)
    work_done = Signal(bool, str)

    def __init__(self, config: AppConfig, root_dir: Path):
        super().__init__()
        self.config = config
        self.root_dir = root_dir
        self._preset_mgr = PresetManager(root_dir / "配置文件" / "参数预设")
        self._import_reference_presets()
        if not self._preset_mgr.list_presets():
            self._preset_mgr.save("默认预设", config)

        self.setWindowTitle("风无忧 · 视频剪辑软件")
        self.setGeometry(80, 50, 1500, 900)
        self.setMinimumSize(1280, 720)
        self.setStyleSheet(DARK_QSS)

        self.log_received.connect(self._on_log)
        self.progress_received.connect(self._on_progress)
        self.work_done.connect(self._on_done)
        self._worker = BatchWorker(
            log_callback=self.log_received.emit,
            progress_callback=self.progress_received.emit,
            done_callback=self.work_done.emit,
        )

        self._setup_ui()

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
        brand = QLabel("BLACKCAT FLOWCUT")
        brand.setObjectName("brand")
        header_layout.addWidget(brand)
        brand_sub = QLabel("VIDEO COMPOSER")
        brand_sub.setObjectName("brandSub")
        header_layout.addWidget(brand_sub)
        tutorial = QPushButton("更新与教程")
        tutorial.setFlat(True)
        header_layout.addWidget(tutorial)
        header_layout.addStretch()
        self._status_label = QLabel("● 就绪")
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
        channel_brand = QLabel("BLACKCAT")
        channel_brand.setObjectName("channelBrand")
        channel_layout.addWidget(channel_brand)
        channel_caption = QLabel("FLOWCUT STUDIO")
        channel_caption.setObjectName("brandSub")
        channel_layout.addWidget(channel_caption)
        channel_layout.addSpacing(18)
        channel_layout.addWidget(QLabel("选择通道"))

        self._channel_group = QButtonGroup(self)
        self._channel_group.setExclusive(True)
        channels = (
            ("01", "HDH 蒙版通道", 0),
        )
        for number, name, tab_index in channels:
            button = QPushButton(f"{number}   {name}")
            button.setObjectName("channelButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, index=tab_index: self._select_channel(index)
            )
            self._channel_group.addButton(button)
            channel_layout.addWidget(button)
            if tab_index == 0:
                button.setChecked(True)
        channel_layout.addStretch()
        channel_footer = QLabel("BLACK CAT VIDEO")
        channel_footer.setObjectName("brandSub")
        channel_layout.addWidget(channel_footer)
        splitter.addWidget(channel_panel)

        # Left: folders, controls, presets and log.
        left_panel = QFrame()
        left_panel.setObjectName("sidebar")
        left_panel.setMinimumWidth(320)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 4, 5, 5)
        left_layout.setSpacing(5)
        self._files_page = FilesPage(self.config)
        left_layout.addWidget(self._files_page, 4)

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
        self._btn_test = QPushButton("🔍 检查视频")
        self._btn_test.clicked.connect(self._on_self_test)
        row.addWidget(self._btn_test)
        clear_log = QPushButton("清空日志")
        clear_log.clicked.connect(self._log_clear)
        row.addWidget(clear_log)
        controls_layout.addLayout(row)

        batch_row = QHBoxLayout()
        self._delete_aux = QCheckBox("删除已用辅助视频")
        self._delete_aux.setChecked(self.config.delete_used_aux)
        self._delete_aux.toggled.connect(
            lambda value: setattr(self.config, "delete_used_aux", value)
        )
        batch_row.addWidget(self._delete_aux)
        batch_row.addStretch()
        batch_row.addWidget(QLabel("每个素材处理次数："))
        self._repeat_count = QSpinBox()
        self._repeat_count.setRange(1, 100)
        self._repeat_count.setValue(self.config.repeat_count)
        self._repeat_count.valueChanged.connect(
            lambda value: setattr(self.config, "repeat_count", value)
        )
        batch_row.addWidget(self._repeat_count)
        controls_layout.addLayout(batch_row)

        row = QHBoxLayout()
        row.addWidget(QLabel("参数预设："))
        self._preset_combo = QComboBox()
        row.addWidget(self._preset_combo, 1)
        self._btn_load_preset = QPushButton("应用")
        self._btn_load_preset.clicked.connect(self._on_load_preset)
        row.addWidget(self._btn_load_preset)
        self._btn_save_preset = QPushButton("存为")
        self._btn_save_preset.clicked.connect(self._on_save_preset)
        row.addWidget(self._btn_save_preset)
        self._btn_delete_preset = QPushButton("删除")
        self._btn_delete_preset.setObjectName("danger")
        self._btn_delete_preset.clicked.connect(self._on_delete_preset)
        row.addWidget(self._btn_delete_preset)
        controls_layout.addLayout(row)
        self._refresh_presets()
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self._progress.hide()
        controls_layout.addWidget(self._progress)
        left_layout.addWidget(controls)
        left_layout.addSpacing(24)
        self._log = LogPanel("处理日志")
        left_layout.addWidget(self._log, 5)
        splitter.addWidget(left_panel)

        # Center: large preview canvas.
        center_panel = QFrame()
        center_panel.setObjectName("panel")
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(7, 5, 7, 7)
        preview_bar = QHBoxLayout()
        preview_title = QLabel("● 可视化预览（与导出参数同步）")
        preview_title.setStyleSheet("color:#25e7f4; font-weight:700")
        preview_bar.addWidget(preview_title)
        preview_bar.addStretch()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._preview_refresh)
        preview_bar.addWidget(refresh)
        center_layout.addLayout(preview_bar)
        self._preview = PreviewCanvas(self.config, self.root_dir)
        center_layout.addWidget(self._preview, 1)
        hint = QLabel("⚠ 请选择有效的主视频和辅助视频文件夹")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color:#b3a26b")
        center_layout.addWidget(hint)
        splitter.addWidget(center_panel)

        # Right: reference-style compact parameter tabs.
        right_panel = QFrame()
        right_panel.setObjectName("panel")
        right_panel.setMinimumWidth(430)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        self._tabs = QTabWidget()
        self._tabs.tabBar().setExpanding(True)
        self._tabs.tabBar().setUsesScrollButtons(False)
        pip_page = PipPage(self.config)
        sticker_page = StickerPage(self.config)
        picture_page = QWidget()
        picture_layout = QVBoxLayout(picture_page)
        picture_layout.setContentsMargins(0, 0, 0, 0)
        picture_tabs = QTabWidget()
        picture_tabs.addTab(pip_page, "画中画")
        picture_tabs.addTab(sticker_page, "贴纸/扫光")
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
            ("字幕设置", self._pages["字幕设置"]),
            ("人脸遮挡", self._pages["人脸遮挡"]),
            ("卡秒", self._pages["卡秒"]),
        )
        for name, page in tabs:
            self._tabs.addTab(page, name)
        right_layout.addWidget(self._tabs, stretch=1)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setStretchFactor(3, 0)
        splitter.setSizes([180, 340, 700, 470])
        root_layout.addWidget(splitter, stretch=1)

    def _preview_refresh(self) -> None:
        self._preview.schedule_refresh()

    def _select_channel(self, tab_index: int) -> None:
        self._tabs.setCurrentIndex(tab_index)

    def _import_reference_presets(self) -> None:
        candidates = list(
            self.root_dir.parent.glob(
                "风无忧剪辑软件V1.6_1/*/配置文件/参数预设"
            )
        )
        if not candidates:
            return
        for path in candidates[0].glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                config = AppConfig.from_dict(data)
                reference_root = candidates[0].parent.parent
                if (reference_root / "saoguang").is_dir():
                    config.scanlight_folder = str(reference_root / "saoguang")
                if (reference_root / "kaimu").is_dir():
                    config.kaimu_folder = str(reference_root / "kaimu")
                self._preset_mgr.save(path.stem, config)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue

    def _log_clear(self) -> None:
        if hasattr(self, "_log"):
            self._log.clear()

    # ═══════════════════════════════════════
    # 操作回调
    # ═══════════════════════════════════════

    def _on_start(self) -> None:
        """开始批量处理。"""
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
        self._set_status("● 正在处理", "#fbbf24")
        self._progress.setRange(0, 0)
        self._progress.show()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_test.setEnabled(False)

        self._worker.start(self.config, self.root_dir)

    def _on_stop(self) -> None:
        """停止处理。"""
        self._worker.cancel()
        self._btn_stop.setEnabled(False)

    def _on_self_test(self) -> None:
        """环境自检。"""
        self._log.clear()
        self._log.append("═══ 环境自检 ═══", "#93c5fd")
        self._set_status("● 自检中", "#93c5fd")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(False)
        self._btn_test.setEnabled(False)
        self._worker.start_self_test(self.root_dir)

    def _on_open_output(self) -> None:
        """打开成品目录。"""
        self._save_config()
        output = self._resolve(self.config.output_folder)
        output.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(output.resolve())])

    def _on_save_preset(self) -> None:
        """保存为预设。"""
        name, ok = QInputDialog.getText(self, "保存预设", "请输入预设名称：")
        if not ok or not name.strip():
            return
        if self._preset_mgr.save(name.strip(), self.config):
            self._refresh_presets(name.strip())
            self._set_status(f"● 预设 [{name.strip()}] 已保存", "#86efac")
        else:
            QMessageBox.warning(self, "错误", "保存预设失败。")

    def _on_load_preset(self) -> None:
        """加载预设。"""
        name = self._preset_combo.currentText()
        if not name:
            QMessageBox.information(self, "提示", "没有已保存的预设。")
            return

        loaded = self._preset_mgr.load(name)
        if loaded is None:
            QMessageBox.warning(self, "错误", "加载预设失败。")
            return

        # 更新 config
        for field in AppConfig.__dataclass_fields__:
            setattr(self.config, field, getattr(loaded, field))
        for page in self._pages.values():
            for key, row in getattr(page, "_rows", {}).items():
                if hasattr(row, "value"):
                    row.value = getattr(self.config, key)
                elif hasattr(row, "path"):
                    row.path = getattr(self.config, key)
        self._delete_aux.setChecked(self.config.delete_used_aux)
        self._repeat_count.setValue(self.config.repeat_count)

        self._set_status(f"● 已加载预设 [{name}]", "#93c5fd")

    def _refresh_presets(self, selected: str = "") -> None:
        names = self._preset_mgr.list_presets()
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItems(names)
        if selected in names:
            self._preset_combo.setCurrentText(selected)
        self._preset_combo.blockSignals(False)

    def _on_delete_preset(self) -> None:
        name = self._preset_combo.currentText()
        if not name:
            return
        if QMessageBox.question(
            self, "删除预设", f"确定删除预设“{name}”吗？"
        ) != QMessageBox.Yes:
            return
        if self._preset_mgr.delete(name):
            self._refresh_presets()

    # ═══════════════════════════════════════
    # Worker 回调
    # ═══════════════════════════════════════

    def _on_log(self, text: str) -> None:
        self._log.append(text)

    def _on_progress(self, current: int, total: int) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(current)

    def _on_done(self, success: bool, message: str) -> None:
        self._progress.hide()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_test.setEnabled(True)
        if success:
            self._set_status("● 就绪", "#86efac")
        else:
            self._set_status("● " + message, "#fda4af")
        self._log.append("--- " + message + " ---", "#94a3b8")

    # ═══════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════

    def _set_status(self, text: str, color: str) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"font-size: 12px; padding: 6px 14px;"
            f"background-color: #162232; border-radius: 12px; color: {color};"
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
