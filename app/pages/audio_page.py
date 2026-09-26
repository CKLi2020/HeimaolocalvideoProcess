"""声音处理：背景音乐混合与原对白轻量变声。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig
from app.pages.template_page import TemplateChoiceRow
from app.widgets.folder_row import FolderRow
from app.widgets.param_row import ParamRow
from engine.ffmpeg_builder import AUDIO_EXTS, list_media


class AudioPage(QWidget):
    def __init__(
        self,
        config: AppConfig,
        root_dir: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self._root = Path(root_dir) if root_dir else Path(".")
        self._rows: dict[str, QWidget] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(16)

        bgm_group = QGroupBox("添加背景音乐")
        bgm_form = QFormLayout(bgm_group)
        bgm_form.setSpacing(10)

        self._add_param(bgm_form, "启用背景音乐", "audio_bgm_enabled", "bool")

        folder = FolderRow(
            placeholder="选择背景音乐文件夹...",
            initial=config.audio_bgm_folder,
        )
        folder.path_changed.connect(self._on_folder_changed)
        bgm_form.addRow("音乐文件夹", folder)
        self._rows["audio_bgm_folder"] = folder

        if config.audio_bgm_pick not in ("随机", "固定"):
            config.audio_bgm_pick = "随机"
        self._add_param(bgm_form, "选择方式", "audio_bgm_pick", "combo:随机,固定")

        self._fixed_row = TemplateChoiceRow(
            placeholder="未选择（点右侧「选择」）",
            current=config.audio_bgm_fixed,
            folder_getter=self._resolve_folder,
            file_filter=_audio_filter(),
            dialog_title="选择背景音乐",
        )
        self._fixed_row.value_changed.connect(self._on_fixed_changed)
        bgm_form.addRow("固定音乐", self._fixed_row)
        self._rows["audio_bgm_fixed"] = self._fixed_row

        self._fixed_hint = QLabel("")
        self._fixed_hint.setObjectName("previewHint")
        self._fixed_hint.setWordWrap(True)
        bgm_form.addRow(self._fixed_hint)
        self._add_param(bgm_form, "背景音乐音量 %", "audio_bgm_volume", "slider:0-100")
        layout.addWidget(bgm_group)

        voice_group = QGroupBox("原始对白变声")
        voice_form = QFormLayout(voice_group)
        voice_form.setSpacing(10)
        self._add_param(
            voice_form, "智能自适应音色变声", "audio_voice_adaptive", "bool"
        )
        self._add_param(voice_form, "启用手动移调", "audio_voice_enabled", "bool")
        self._add_param(voice_form, "音高（半音）", "audio_voice_pitch", "slider:-6-6")
        self._voice_hint = QLabel("")
        self._voice_hint.setObjectName("previewHint")
        self._voice_hint.setWordWrap(True)
        voice_form.addRow(self._voice_hint)
        layout.addWidget(voice_group)
        layout.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.reload_audio()
        self._update_enabled()

    def _add_param(self, form: QFormLayout, label: str, key: str, kind: str) -> None:
        row = ParamRow(label, kind, getattr(self.config, key))
        row.value_changed.connect(lambda value, k=key: self._on_param_changed(k, value))
        form.addRow(row)
        self._rows[key] = row

    def _resolve_folder(self) -> Path:
        folder = Path(self.config.audio_bgm_folder)
        return folder if folder.is_absolute() else self._root / folder

    def _on_folder_changed(self, value: str) -> None:
        self.config.audio_bgm_folder = value
        self.reload_audio()

    def _on_fixed_changed(self, value: str) -> None:
        self.config.audio_bgm_fixed = value
        self._refresh_hint()

    def _on_param_changed(self, key: str, value) -> None:
        setattr(self.config, key, value)
        if key in (
            "audio_bgm_enabled", "audio_bgm_pick", "audio_voice_enabled",
            "audio_voice_adaptive",
        ):
            self._update_enabled()

    def _update_enabled(self) -> None:
        bgm = self.config.audio_bgm_enabled
        for key in ("audio_bgm_folder", "audio_bgm_pick", "audio_bgm_volume"):
            self._rows[key].setEnabled(bgm)
        self._fixed_row.setEnabled(bgm and self.config.audio_bgm_pick == "固定")
        adaptive = self.config.audio_voice_adaptive
        self._rows["audio_voice_enabled"].setEnabled(not adaptive)
        self._rows["audio_voice_pitch"].setEnabled(
            self.config.audio_voice_enabled and not adaptive
        )
        self._voice_hint.setText(
            "已启用智能模式：自动分析对白声线并轻微调整音色，语速和时长不变。"
            if adaptive else
            "手动模式：负数更低沉，正数更明亮；视频和对白时长不变。"
        )
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        if not self.config.audio_bgm_enabled or self.config.audio_bgm_pick != "固定":
            self._fixed_hint.setText("")
        elif not self.config.audio_bgm_fixed:
            self._fixed_hint.setText("还没选音乐，出片时会随机挑一首。")
        elif self.config.audio_bgm_fixed not in self._fixed_row.available:
            self._fixed_hint.setText("固定音乐不在当前文件夹里，出片时会退回随机选择。")
        else:
            self._fixed_hint.setText("整批片子都使用这一首背景音乐。")

    def reload_audio(self) -> None:
        names = [path.name for path in list_media(str(self._resolve_folder()), AUDIO_EXTS)]
        self._fixed_row.set_available(names)
        self._refresh_hint()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.reload_audio()


def _audio_filter() -> str:
    patterns = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTS))
    return f"音频 ({patterns});;所有文件 (*)"
