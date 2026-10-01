"""集成的黑猫本地多平台视频处理页面。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.widgets.log_panel import LogPanel
from engine.local_processor import LocalProcessorService
from modes.base_mode import VIDEO_EXTS


class LocalProcessorPage(QWidget):
    log_received = Signal(str)
    progress_received = Signal(float)
    done_received = Signal(int, int, int, str, bool)

    def __init__(self, root_dir: Path, parent=None):
        super().__init__(parent)
        self.root_dir = root_dir
        self.service = LocalProcessorService()
        self.current_mode = None
        self._aux_saved_value = ""
        self._platforms = {}
        self.log_received.connect(self._append_log)
        self.progress_received.connect(self._set_progress)
        self.done_received.connect(self._on_done)
        self._build_ui()
        self._load_modes()
        self._show_environment()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        files = QGroupBox("文件配置（选择文件夹即可批量处理）")
        files_layout = QGridLayout(files)
        self.main_edit = self._path_row(files_layout, 0, "主视频：", True)
        self.aux_edit = self._path_row(files_layout, 1, "辅视频：", True)
        self.output_edit = self._path_row(files_layout, 2, "输出路径：", False)
        self.output_edit.setText(str(self.root_dir / "output"))
        layout.addWidget(files)

        modes = QGroupBox("处理平台 / 模式")
        self.mode_grid = QGridLayout(modes)
        self.mode_grid.setSpacing(8)
        layout.addWidget(modes)

        execution = QGroupBox("任务执行")
        execution_layout = QVBoxLayout(execution)
        processor_row = QHBoxLayout()
        processor_row.addWidget(QLabel("处理模式："))
        self.processor = QComboBox()
        if self.service.gpu_profile.get("available"):
            vendor = self.service.gpu_profile.get("vendor_label") or "GPU"
            self.processor.addItem(f"GPU处理 {vendor}", True)
        self.processor.addItem("CPU处理", False)
        processor_row.addWidget(self.processor)
        self.copies_label = QLabel("裂变个数：")
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 100)
        self.copies_spin.setValue(1)
        self.copies_spin.setSuffix(" 份")
        self.copies_label.hide()
        self.copies_spin.hide()
        processor_row.addWidget(self.copies_label)
        processor_row.addWidget(self.copies_spin)
        self.processor_status = QLabel()
        processor_row.addWidget(self.processor_status, 1)
        execution_layout.addLayout(processor_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        execution_layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("▶ 开始处理")
        self.start_button.setObjectName("accent")
        self.start_button.clicked.connect(self.start)
        buttons.addWidget(self.start_button)
        self.stop_button = QPushButton("■ 停止处理")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.stop_button)
        buttons.addStretch()
        execution_layout.addLayout(buttons)
        layout.addWidget(execution)

        notice = QLabel("公告：请遵守法律法规，仅处理拥有合法权利的视频素材。")
        notice.setAlignment(Qt.AlignCenter)
        layout.addWidget(notice)

        self.log = LogPanel("处理日志（本地执行）")
        clear = QPushButton("清空日志")
        clear.clicked.connect(self.log.clear)
        self.log.header_layout.addWidget(clear)
        layout.addWidget(self.log, 1)

    def _path_row(self, layout, row, label, allow_file):
        layout.addWidget(QLabel(label), row, 0)
        edit = QLineEdit()
        edit._path_buttons = []
        layout.addWidget(edit, row, 1)
        if allow_file:
            file_button = QPushButton("选择文件")
            file_button.setObjectName("browse")
            file_button.clicked.connect(lambda: self._choose_file(edit))
            layout.addWidget(file_button, row, 2)
            edit._path_buttons.append(file_button)
        folder_button = QPushButton("选择文件夹" if allow_file else "选择输出目录")
        folder_button.setObjectName("browse")
        folder_button.clicked.connect(lambda: self._choose_folder(edit))
        layout.addWidget(folder_button, row, 3 if allow_file else 2)
        edit._path_buttons.append(folder_button)
        if not allow_file:
            open_button = QPushButton("打开文件夹")
            open_button.setObjectName("browse")
            open_button.clicked.connect(self._open_output)
            layout.addWidget(open_button, row, 3)
        return edit

    def _load_modes(self):
        unavailable = {"TK处理", "百家处理", "哔哩处理", "多多处理"}
        for index, (title, modes) in enumerate(self.service.mode_groups.items()):
            frame = QFrame()
            frame.setObjectName("localModeCard")
            card = QVBoxLayout(frame)
            caption = QLabel(title)
            caption.setObjectName("localModeCaption")
            caption.setStyleSheet("font-weight: 700; color: #d4dff0;")
            caption.setAlignment(Qt.AlignCenter)
            card.addWidget(caption)
            combo = QComboBox()
            for mode in modes:
                combo.addItem(mode.name, mode)
            combo.setEnabled(title not in unavailable)
            combo.activated.connect(lambda _=0, name=title: self._activate(name))
            card.addWidget(combo)
            self.mode_grid.addWidget(frame, index // 4, index % 4)
            self._platforms[title] = (frame, combo)
        if self._platforms:
            self._activate(next(iter(self._platforms)))
        for error in self.service.mode_errors:
            self.log_received.emit("【模式警告】" + str(error))

    def _activate(self, title):
        for name, (frame, combo) in self._platforms.items():
            active = name == title
            frame.setStyleSheet(
                "QFrame#localModeCard { background: %s; border: %s solid %s; border-radius: 8px; }"
                % (("#294267", "2px", "#60a5fa") if active else ("#1b2c49", "1px", "#2c456d"))
            )
            if active:
                self.current_mode = combo.currentData()
        needs_auxiliary = bool(self.current_mode and self.current_mode.needs_aux)
        self._set_auxiliary_enabled(needs_auxiliary)
        supports_copies = bool(getattr(self.current_mode, "supports_copies", False))
        self.copies_label.setVisible(supports_copies)
        self.copies_spin.setVisible(supports_copies)
        if self.current_mode:
            self.log_received.emit(f"当前模式：{title} · {self.current_mode.name}")

    def _set_auxiliary_enabled(self, enabled):
        notice = "本通道不需要辅助视频"
        if not enabled and self.aux_edit.isEnabled():
            self._aux_saved_value = self.aux_edit.text()
            self.aux_edit.setText(notice)
        elif enabled and not self.aux_edit.isEnabled():
            self.aux_edit.setText(self._aux_saved_value)
        self.aux_edit.setEnabled(enabled)
        self.aux_edit.setStyleSheet(
            "" if enabled else "QLineEdit:disabled { color: #ff4d5e; font-weight: 700; }"
        )
        for button in self.aux_edit._path_buttons:
            button.setEnabled(enabled)

    def _show_environment(self):
        profile = self.service.gpu_profile
        if profile.get("available"):
            text = f"处理优先级：GPU优先（{profile.get('vendor_label')}），失败后自动转CPU"
        else:
            text = "未检测到可用 GPU，使用 CPU 处理"
        self.processor_status.setText(text)
        self.log_received.emit("就绪。选择主视频后点击“开始处理”。")
        self.log_received.emit("FFmpeg：" + (self.service.ffmpeg or "未找到"))

    def start(self):
        if self.service.is_running:
            return
        if self.current_mode is None:
            QMessageBox.warning(self, "提示", "没有可用的处理模式。")
            return
        main_value = self.main_edit.text().strip()
        files = self._files(main_value)
        if not files:
            QMessageBox.warning(self, "提示", "请选择有效的主视频文件或文件夹。")
            return
        auxiliary_files = []
        if self.current_mode.needs_aux:
            auxiliary_files = self._files(self.aux_edit.text().strip())
            if not auxiliary_files:
                QMessageBox.warning(self, "提示", "当前模式需要有效的辅视频。")
                return
        if not self.service.ffmpeg or not self.service.ffprobe:
            QMessageBox.warning(self, "提示", "未找到 FFmpeg 或 FFprobe。")
            return

        output = self.output_edit.text().strip() or str(self.root_dir / "output")
        state = {
            "main_video": main_value,
            "aux_video": self.aux_edit.text().strip() if self.current_mode.needs_aux else "",
            "output_dir": output,
            "threads": int(self.service.config.get("default_threads") or 6),
            "bitrate": str(self.service.config.get("default_bitrate") or "6000k"),
            "use_gpu": bool(self.processor.currentData()) and self.service.gpu_profile.get("available"),
            "gpu_profile": self.service.gpu_profile,
            "output_naming": str(self.service.config.get("output_naming") or "hash"),
            "copies": self.copies_spin.value(),
        }
        self.progress.setValue(0)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        copies = self.copies_spin.value() if getattr(self.current_mode, "supports_copies", False) else 1
        self.log_received.emit(f"开始处理：{len(files) * copies} 个任务")
        self.service.start(
            state,
            self.current_mode,
            files,
            auxiliary_files,
            self.log_received.emit,
            self.progress_received.emit,
            self.done_received.emit,
        )

    def stop(self):
        if not self.service.is_running:
            return
        self.service.stop()
        self.stop_button.setEnabled(False)
        self.log_received.emit("已发送停止指令。")

    def _files(self, value):
        path = Path(value)
        if path.is_file() and path.suffix.lower() in VIDEO_EXTS:
            return [path]
        return self.service.list_videos(path)

    def _choose_file(self, edit):
        patterns = " ".join("*" + suffix for suffix in VIDEO_EXTS)
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", f"视频文件 ({patterns})")
        if path:
            edit.setText(path)

    def _choose_folder(self, edit):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹", edit.text())
        if path:
            edit.setText(path)

    def _open_output(self):
        path = Path(self.output_edit.text().strip() or self.root_dir / "output")
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)

    def _append_log(self, text):
        self.log.append(text)

    def _set_progress(self, value):
        self.progress.setValue(round(value))

    def _on_done(self, succeeded, failed, total, output, cancelled):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if cancelled:
            self.log.append("--- 任务已停止 ---", "#fbbf24")
        else:
            self.log.append(f"--- 完成：成功 {succeeded}，失败 {failed}，共 {total} ---")
        if not cancelled and total:
            QMessageBox.information(self, "处理结束", f"成功：{succeeded}\n失败：{failed}\n输出：{output}")
