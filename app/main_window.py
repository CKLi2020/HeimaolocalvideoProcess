"""主窗口：组装所有标签页、预览区、日志区、操作按钮。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)
from PySide6.QtCore import Qt, QTimer

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
    def __init__(self, config: AppConfig, root_dir: Path):
        super().__init__()
        self.config = config
        self.root_dir = root_dir
        self._preset_mgr = PresetManager(root_dir / "配置文件" / "参数预设")

        self.setWindowTitle("FlowCut Studio — 视频批量合成")
        self.setGeometry(100, 60, 1320, 860)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(DARK_QSS)

        self._worker = BatchWorker(
            log_callback=self._on_log,
            progress_callback=self._on_progress,
            done_callback=self._on_done,
        )

        self._setup_ui()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(14, 10, 14, 10)
        root_layout.setSpacing(8)

        # ── 顶部 Header ──
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)

        title = QLabel("FlowCut Studio")
        title.setObjectName("title")
        header_layout.addWidget(title)

        subtitle = QLabel("  视频批量合成")
        subtitle.setObjectName("subtitle")
        header_layout.addWidget(subtitle)

        header_layout.addStretch()

        self._status_label = QLabel("● 就绪")
        self._status_label.setObjectName("status")
        header_layout.addWidget(self._status_label)

        root_layout.addWidget(header)

        # ── 模式导航 ──
        mode_bar = QWidget()
        mode_layout = QHBoxLayout(mode_bar)
        mode_layout.setContentsMargins(8, 2, 8, 2)
        mode_layout.setSpacing(4)
        self._mode_buttons: dict[str, QPushButton] = {}
        for mode_name in ["鹤漫剪辑", "语音识别", "人脸处理", "MP4工具"]:
            btn = QPushButton(mode_name)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { background: #1a2632; color: #8899a6; border: 1px solid #2d3a47; "
                "border-radius: 4px; padding: 5px 14px; font-size: 11px; }"
                "QPushButton:checked { background: #6366f1; color: white; border-color: #6366f1; }"
                "QPushButton:hover:!checked { background: #1f2d3b; color: #c4c9ef; }"
            )
            btn.clicked.connect(lambda checked, n=mode_name: self._switch_mode(n))
            mode_layout.addWidget(btn)
            self._mode_buttons[mode_name] = btn
        self._mode_buttons["鹤漫剪辑"].setChecked(True)
        mode_layout.addStretch()
        root_layout.addWidget(mode_bar)

        # ── 分割线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #2d3a47; max-height: 1px;")
        root_layout.addWidget(sep)

        # ── 主体 Splitter ──
        splitter = QSplitter(Qt.Horizontal)

        # 左侧面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(10)

        # 预览区
        preview_header = QLabel("实时预览")
        preview_header.setStyleSheet("color: #f0f4f8; font-weight: bold; font-size: 13px;")
        left_layout.addWidget(preview_header)

        self._preview = PreviewCanvas(self.config, self.root_dir)
        left_layout.addWidget(self._preview, stretch=1)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self._progress.hide()
        left_layout.addWidget(self._progress)

        # 操作按钮
        actions = QWidget()
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)

        self._btn_start = QPushButton("▶  开始处理")
        self._btn_start.setObjectName("accent")
        self._btn_start.clicked.connect(self._on_start)
        actions_layout.addWidget(self._btn_start)

        btn_row = QHBoxLayout()
        self._btn_stop = QPushButton("■  停止")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_stop.setEnabled(False)
        btn_row.addWidget(self._btn_stop)

        self._btn_test = QPushButton("🔧  环境检查")
        self._btn_test.clicked.connect(self._on_self_test)
        btn_row.addWidget(self._btn_test)
        actions_layout.addLayout(btn_row)

        self._btn_output = QPushButton("📂  打开成品目录")
        self._btn_output.clicked.connect(self._on_open_output)
        actions_layout.addWidget(self._btn_output)

        self._btn_save_preset = QPushButton("💾  存为预设")
        self._btn_save_preset.clicked.connect(self._on_save_preset)
        actions_layout.addWidget(self._btn_save_preset)

        self._btn_load_preset = QPushButton("📋  加载预设")
        self._btn_load_preset.clicked.connect(self._on_load_preset)
        actions_layout.addWidget(self._btn_load_preset)

        left_layout.addWidget(actions)

        splitter.addWidget(left_panel)

        # 右侧面板：标签页 + 日志
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._tabs = QTabWidget()

        self._pages = {
            "文件与批量": FilesPage(self.config),
            "画布与编码": CanvasPage(self.config),
            "蒙版与横条": MaskPage(self.config),
            "画中画与动态": PipPage(self.config),
            "贴纸与扫光": StickerPage(self.config),
            "开幕、封面与字幕": OpeningPage(self.config),
            "人脸、调色与后处理": FaceColorPage(self.config),
        }
        for name, page in self._pages.items():
            self._tabs.addTab(page, name)

        right_layout.addWidget(self._tabs, stretch=1)

        # 日志
        self._log = LogPanel("任务日志")
        right_layout.addWidget(self._log)

        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([330, 950])

        root_layout.addWidget(splitter, stretch=1)

    # ═══════════════════════════════════════
    # 操作回调
    # ═══════════════════════════════════════

    def _on_start(self) -> None:
        """开始批量处理。"""
        # 基本校验
        if not self.config.main_folder or not self.config.background_folder:
            QMessageBox.warning(self, "提示", "请先设置主素材文件夹和辅助视频文件夹。")
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
            self._set_status(f"● 预设 [{name.strip()}] 已保存", "#86efac")
        else:
            QMessageBox.warning(self, "错误", "保存预设失败。")

    def _on_load_preset(self) -> None:
        """加载预设。"""
        presets = self._preset_mgr.list_presets()
        if not presets:
            QMessageBox.information(self, "提示", "没有已保存的预设。")
            return

        # 简单列表选择
        from PySide6.QtWidgets import QInputDialog as QID
        name, ok = QID.getItem(self, "加载预设", "选择预设：", presets, 0, False)
        if not ok or not name:
            return

        loaded = self._preset_mgr.load(name)
        if loaded is None:
            QMessageBox.warning(self, "错误", "加载预设失败。")
            return

        # 更新 config
        for field in AppConfig.__dataclass_fields__:
            setattr(self.config, field, getattr(loaded, field))

        self._set_status(f"● 已加载预设 [{name}]", "#93c5fd")

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
        for name, btn in self._mode_buttons.items():
            btn.setChecked(name == mode)
        mode_to_tab = {
            "鹤漫剪辑": 0,
            "语音识别": 5,
            "人脸处理": 6,
            "MP4工具": 6,
        }
        idx = mode_to_tab.get(mode, 0)
        self._tabs.setCurrentIndex(idx)

    def _save_config(self) -> None:
        """回写配置到 config.json。"""
        config_path = self.root_dir / "config.json"
        self.config.to_json(config_path)
