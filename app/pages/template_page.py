"""模板 标签页。

模板铺满画布盖在主视频之上，中央窗口挖空让主视频透出来，四周是模板。
模型参考「穿山甲」的 蒙版区域/羽化宽度/填充方式，详见 engine/template_lib.py。

主视频**不缩小**，仍是整块画布、尺寸位置都不变（= 填充方式「全屏」），
窗口外的模板直接盖住它。所以下面这几个窗口字段只影响主视频的 alpha，
「适配 / 全屏」仍然复用基础参数页的 main_fit 开关，管的是主视频自身
在画布里的摆放，与窗口无关。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig
from app.widgets.folder_row import FolderRow
from app.widgets.param_row import ParamRow


class TemplatePage(QWidget):
    def __init__(
        self,
        config: AppConfig,
        root_dir: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self._root = Path(root_dir) if root_dir else Path(".")
        self._rows: dict[str, FolderRow | ParamRow | TemplateChoiceRow] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        root_layout = QVBoxLayout(inner)
        root_layout.setSpacing(16)

        # ── 模板库 ──
        lib_group = QGroupBox("模板库")
        lib_form = QFormLayout(lib_group)
        lib_form.setSpacing(10)

        self._folder_row = FolderRow(
            placeholder="选择模板文件夹...",
            initial=str(getattr(config, "tpl_folder", "")),
        )
        self._folder_row.path_changed.connect(
            lambda v: self._on_folder_changed(v)
        )
        lib_form.addRow("模板文件夹", self._folder_row)
        self._rows["tpl_folder"] = self._folder_row

        # 两种选法：随机（每条片子换一张）/ 固定（整批都用同一张，自己挑）。
        # 老的「顺序」已去掉；配置里若还留着这个值，下面 _normalize_pick 会把它
        # 归成「随机」，免得下拉显示的和引擎实际做的不是一回事。
        self._normalize_pick()

        lib_params = [
            ("启用模板", "tpl_enabled", "bool"),
            ("选择方式", "tpl_pick", "combo:随机,固定"),
        ]
        for label, key, ptype in lib_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(
                lambda v, k=key: self._on_param_changed(k, v)
            )
            lib_form.addRow(row)
            self._rows[key] = row

        # 固定模板：只显示文件名 + 一个「选择」按钮，按钮从模板文件夹里挑。
        self._fixed_row = TemplateChoiceRow(
            placeholder="未选择（点右侧「选择」）",
            current=str(getattr(config, "tpl_fixed", "")),
            folder_getter=self._resolve_folder,
        )
        self._fixed_row.value_changed.connect(
            lambda v: self._on_fixed_changed(v)
        )
        lib_form.addRow("固定模板", self._fixed_row)
        self._rows["tpl_fixed"] = self._fixed_row

        # 固定项失效（模板被删或改名）时出片会**静默**退回随机，用户只会觉得
        # 「选了固定却没用」。这里当场说明白。
        self._fixed_hint = QLabel("")
        self._fixed_hint.setObjectName("previewHint")
        self._fixed_hint.setWordWrap(True)
        lib_form.addRow(self._fixed_hint)

        root_layout.addWidget(lib_group)

        # ── 中央窗口 ──
        # 全局默认值：所有模板共用这一套窗口几何。
        win_group = QGroupBox("中央窗口（全局，所有模板共用）")
        win_form = QFormLayout(win_group)
        win_form.setSpacing(10)

        win_params = [
            ("窗口宽 %", "tpl_window_w", "slider:10-100"),
            ("窗口高 %", "tpl_window_h", "slider:10-100"),
            ("窗口中心 X %", "tpl_window_center_x", "slider:0-100"),
            ("窗口中心 Y %", "tpl_window_center_y", "slider:0-100"),
            ("边缘羽化", "tpl_window_feather", "slider:0-200"),
        ]
        for label, key, ptype in win_params:
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(lambda v, k=key: _setattr(config, k, v))
            win_form.addRow(row)
            self._rows[key] = row

        root_layout.addWidget(win_group)
        root_layout.addStretch()

        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.reload_templates()
        self._update_fixed_enabled()

    # ── 模板目录与固定模板 ──

    def _resolve_folder(self) -> Path:
        folder = Path(str(getattr(self.config, "tpl_folder", "")))
        return folder if folder.is_absolute() else self._root / folder

    def _normalize_pick(self) -> None:
        """把不认识的选择方式归成「随机」。

        例如老的配置文件里存着「顺序」——界面上已经没有这个选项了，不归一的话
        下拉会显示「随机」而引擎照旧按「顺序」跑，界面和成品对不上。
        """
        if getattr(self.config, "tpl_pick", "随机") not in ("随机", "固定"):
            self.config.tpl_pick = "随机"

    def _on_folder_changed(self, value: str) -> None:
        _setattr(self.config, "tpl_folder", value)
        self.reload_templates()

    def _on_param_changed(self, key: str, value) -> None:
        _setattr(self.config, key, value)
        if key == "tpl_pick":
            self._update_fixed_enabled()

    def _on_fixed_changed(self, value: str) -> None:
        _setattr(self.config, "tpl_fixed", value)
        # 先把 config 写好再刷提示，否则提示读到的还是旧值。
        self._refresh_fixed_hint()

    def _update_fixed_enabled(self) -> None:
        # 选了「随机」就把这一行整行置灰：这时挑哪一张都不生效。
        self._fixed_row.setEnabled(
            getattr(self.config, "tpl_pick", "随机") == "固定"
        )
        self._refresh_fixed_hint()

    def _refresh_fixed_hint(self) -> None:
        if getattr(self.config, "tpl_pick", "随机") != "固定":
            self._fixed_hint.setText("")
            return
        name = str(getattr(self.config, "tpl_fixed", "") or "")
        if not name:
            self._fixed_hint.setText("还没选模板，出片时会随机挑一张。")
        elif not self._fixed_row.available:
            # 列表还没扫（构造顺序）时不下结论，避免误报「不在文件夹里」。
            self._fixed_hint.setText("")
        elif name not in self._fixed_row.available:
            self._fixed_hint.setText(
                f"「{name}」不在模板文件夹里（可能已删除或改名），"
                "出片时会退回随机选择。"
            )
        else:
            self._fixed_hint.setText("整批片子都用这一张。")

    def reload_templates(self) -> None:
        """重扫模板目录：更新可选项，并核对已选的那张还在不在。"""
        from engine.template_lib import load_library

        # 和引擎同一套加载逻辑（同一个清单参数），所以这里认为「在库里」的
        # 与出片时真能挑到的一模一样。
        library = load_library(self._resolve_folder(), self.config.tpl_manifest)
        self._fixed_row.set_available(sorted(spec.path.name for spec in library.specs))
        self._fixed_hint.setText("")  # 先清掉，_refresh_fixed_hint 会重算
        self._refresh_fixed_hint()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        # 每次切到这一页都重扫一次：用户可能刚往模板文件夹里丢了新模板，
        # 只在构造时扫一遍的话看不出来。
        self.reload_templates()


class TemplateChoiceRow(QWidget):
    """「固定模板」：只显示**文件名** + 一个「选择」按钮。

    为什么不是下拉：模板可能有几十个、名字又长（`01_无向日葵浅色鲜花动态背景_粉色玫瑰_10秒.mp4`），
    下拉里翻起来比在文件夹里看缩略图还难认。所以按用户的要求给一个按钮，
    打开文件对话框直接从模板文件夹里挑。

    为什么只显示文件名而不是完整路径：配置里也只存文件名（引擎是拿名字在库里
    匹配的，见 TemplateLibrary.pick），存路径会在模板目录整体搬走后失效。
    这里也不给手打 —— 名字打错只会静默退回随机，而对话框只让人从模板目录里选，
    从源头上就不会选到库外的东西。
    """

    value_changed = Signal(object)

    def __init__(
        self,
        placeholder: str = "",
        current: str = "",
        folder_getter: Optional[Callable[[], Path]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._placeholder = placeholder
        self._value = str(current or "")
        self._available: list[str] = []
        # 对话框的起始目录，同时也是「选中的文件必须在库里」的判定依据。
        self._folder_getter: Callable[[], Path] = folder_getter or (lambda: Path("."))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setToolTip("点右边的「选择」，从模板文件夹里挑一张")
        layout.addWidget(self.edit, stretch=1)

        self.button = QPushButton("选择")
        self.button.setObjectName("browse")
        self.button.setFixedWidth(56)
        self.button.clicked.connect(self._browse)
        layout.addWidget(self.button)

        self.edit.setText(self._value)

    # ── 可选项（由 TemplatePage.reload_templates 喂进来） ──

    @property
    def available(self) -> list[str]:
        return list(self._available)

    def set_available(self, names: list[str]) -> None:
        self._available = list(names)
        # 模板文件夹里一个视频都没有时按钮没意义（对话框打开也是空的）。
        # 注意只动按钮、不动自己这一行的 enabled：整行置灰是「选择方式=随机」
        # 的事，归 TemplatePage._update_fixed_enabled 管。
        self.button.setEnabled(bool(names))
        self.edit.setPlaceholderText(
            self._placeholder if names else "模板文件夹里没有视频"
        )

    # ── 取值 ──

    @property
    def value(self) -> str:
        return self._value

    @value.setter
    def value(self, v: str) -> None:
        v = str(v or "")
        if v == self._value:
            return
        self._value = v
        self.edit.setText(v)
        self.value_changed.emit(v)

    # ── 选择 ──

    def _browse(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "选择模板", str(self._folder_getter()), _video_filter(),
        )
        if not chosen:
            return
        name = self.resolve_choice(chosen)
        if name is None:
            QMessageBox.warning(
                self,
                "模板不在这里",
                f"模板只能从模板文件夹里选：\n{self._folder_getter()}\n\n"
                f"把「{Path(chosen).name}」放进这个文件夹，"
                "或改上面的「模板文件夹」。",
            )
            return
        self.value = name

    def resolve_choice(self, chosen: str) -> Optional[str]:
        """对话框选中的文件 → 要写进 config 的文件名；不在模板文件夹里则 None。

        纯函数、不弹窗，逻辑都在这里，方便直接测。
        """
        picked = Path(chosen)
        try:
            if not picked.is_file():
                return None
            parent = picked.resolve().parent
            folder = Path(self._folder_getter()).resolve()
        except OSError:
            return None
        # Windows 路径大小写不敏感，normcase 之后比。
        if os.path.normcase(str(parent)) != os.path.normcase(str(folder)):
            return None
        return picked.name


def _video_filter() -> str:
    """文件对话框的后缀过滤：与引擎认识的视频后缀同一套。"""
    from engine.ffmpeg_builder import VIDEO_EXTS

    patterns = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTS))
    return f"视频 ({patterns});;所有文件 (*)"


def _setattr(obj, key, value):
    try:
        if hasattr(obj, key):
            setattr(obj, key, value)
    except Exception:
        pass
