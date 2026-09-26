"""移动贴纸 标签页。

移动贴纸是在画面上来回漂的贴图。每个贴纸走一条自己的轨道：
位置按 (W-w)*m*(1±sin)、周期按自己的秒数来回摆。

**这一页是移动贴纸唯一的入口** —— 参数全在界面上填，不用去改 config.json
里的 mover_layers_json（那串 JSON 只是这里的读写存储，别的地方不碰它）。
出片管线和预览都调 engine/ffmpeg_builder.py 的 build_mover_layers 取轨道，
和这里「数量滑条 → 行数」用的是同一个函数，所以界面上几行、片子里就几个。

「移动贴纸数量」和下面的行数是同一个东西：拖滑条会直接增删行，不会有
「滑条说 5 个、列表里只有 2 行」这种两处各说各话的状态。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig
from app.widgets.folder_row import FolderRow
from app.widgets.param_row import ParamRow

# 每个贴纸行里可填的项：(标签, JSON 键, 控件类型, 缺省值)
MOVER_FIELDS = (
    ("缩放 %", "scale", "slider:5-200", 45),
    ("不透明度 %", "opacity", "slider:0-100", 100),
    ("水平位置 %", "x", "slider:-50-50", -50),
    ("垂直位置 %", "y", "slider:-50-50", -50),
    ("周期（秒）", "period", "slider:1-60", 8),
)

# 轨道随机时这两项由每次出片重掷，界面上填了也不生效，置灰并给出原因。
ROLLED_KEYS = ("x", "y")


class MoverPage(QWidget):
    preview_changed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self._rows: dict[str, FolderRow | ParamRow] = {}
        self._layer_boxes: list[QGroupBox] = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        self._layout = QVBoxLayout(inner)
        self._layout.setSpacing(12)

        # ── 移动贴纸（全局）──
        group = QGroupBox("移动贴纸")
        form = QFormLayout(group)
        form.setSpacing(10)

        self._folder_row = FolderRow(
            placeholder="选择移动贴图的文件夹...",
            initial=str(getattr(config, "moving_sticker_folder", "")),
        )
        self._folder_row.path_changed.connect(
            lambda v: _setattr(config, "moving_sticker_folder", v)
        )
        form.addRow("贴图文件夹", self._folder_row)
        self._rows["moving_sticker_folder"] = self._folder_row

        for label, key, ptype in (
            ("启用移动贴纸", "moving_sticker_enabled", "bool"),
            ("移动贴纸数量", "mover_count", "slider:1-20"),
            ("每次随机轨道", "mover_random", "bool"),
            ("默认周期（秒）", "moving_sticker_period", "slider:1-60"),
        ):
            row = ParamRow(label, ptype, getattr(config, key))
            row.value_changed.connect(
                lambda value, name=key: self._on_global_changed(name, value)
            )
            form.addRow(row)
            self._rows[key] = row

        self._layout.addWidget(group)

        # 提示文字由 _refresh_hint 按状态填：关闭了说明出片不带移动贴纸，
        # 开着随机说明位置那两行为什么填了不生效。
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setObjectName("previewHint")
        self._layout.addWidget(self._hint)

        # ── 每个贴纸一组 ──
        self._layers_layout = QVBoxLayout()
        self._layers_layout.setSpacing(12)
        self._layout.addLayout(self._layers_layout)

        self._add_button = QPushButton("＋ 增加移动贴纸")
        self._add_button.clicked.connect(self._add_layer)
        self._layout.addWidget(self._add_button)
        self._layout.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # 打开时先把行数与数量对齐，免得界面上显示 2 行、片子里出 5 个。
        self._sync_count(int(getattr(config, "mover_count", 1) or 1))
        self._rebuild_layers()

    # ── 全局项的联动 ──

    def _on_global_changed(self, key: str, value) -> None:
        # 先落配置：下面几个分支只管界面联动。少了这一句，「启用移动贴纸」
        # 「每次随机轨道」「默认周期」在界面上改了都不进 config，出片照旧按
        # 旧值走 —— 开关点了没反应就是这个原因。
        _setattr(self.config, key, value)

        if key == "mover_count":
            # 数量滑条直接决定列表长度，条数和滑条永远一致。
            self._sync_count(int(value))
            self._rebuild_layers()
            self.preview_changed.emit()
        elif key == "mover_random":
            # 只是切换「位置能不能填」，重画一遍让那两行跟着置灰/恢复。
            self._rebuild_layers()
            self.preview_changed.emit()
        elif key == "moving_sticker_enabled":
            # 关掉就整页置灰（只留这个开关本身能点，不然关掉就再也开不回来）。
            self._apply_enabled_state()
            self.preview_changed.emit()

    def _sync_count(self, count: int) -> None:
        """把 mover_layers_json 补齐/裁剪成 count 条。"""
        from engine.ffmpeg_builder import build_mover_layers

        count = max(1, int(count))
        self.config.mover_count = count
        layers = build_mover_layers(
            count, self._layers(),
            int(getattr(self.config, "mover_scale", 45)),
            int(getattr(self.config, "mover_opacity", 100)),
            int(getattr(self.config, "moving_sticker_period", 8)),
        )
        self._save_layers(layers)

    # ── 轨道列表的读写 ──

    def _layers(self) -> list[dict]:
        import json

        try:
            layers = json.loads(self.config.mover_layers_json or "[]")
            if isinstance(layers, list):
                return [l for l in layers if isinstance(l, dict)]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def _save_layers(self, layers: list[dict]) -> None:
        import json

        self.config.mover_layers_json = json.dumps(layers, ensure_ascii=False)

    def _rebuild_layers(self) -> None:
        while self._layers_layout.count():
            item = self._layers_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 行里的键带下标放 _rows：同一个页面里会有好几行都叫「缩放 %」，
        # 不带下标的键会互相覆盖，联动也就只连上最后一行。
        for key in list(self._rows):
            if key.startswith("mover_layer_"):
                del self._rows[key]

        self._layer_boxes: list[QGroupBox] = []

        for index, layer in enumerate(self._layers()):
            box = QGroupBox(f"移动贴纸 {index + 1}")
            form = QFormLayout(box)
            for label, key, ptype, default in MOVER_FIELDS:
                row = ParamRow(label, ptype, layer.get(key, default))
                row.value_changed.connect(
                    lambda value, i=index, name=key: self._update_layer(i, name, value)
                )
                form.addRow(row)
                self._rows[f"mover_layer_{index}_{key}"] = row
            delete_button = QPushButton("删除此移动贴纸")
            delete_button.setObjectName("danger")
            delete_button.clicked.connect(
                lambda checked=False, i=index: self._delete_layer(i)
            )
            form.addRow(delete_button)
            self._layers_layout.addWidget(box)
            self._layer_boxes.append(box)

        # 行建好之后再统一决定谁灰谁亮：置灰有两条互不相干的理由（功能关了、
        # 位置会被重掷），分散在两处设会互相覆盖。
        self._apply_enabled_state()

    def _apply_enabled_state(self) -> None:
        """一页之内的置灰规则，集中在这里。

        1. 「启用移动贴纸」关掉 → 除这个开关本身外整页置灰。开关自己必须留着
           能点，否则关掉之后就再也开不回来了。出片侧看的是同一个 config 字段
           （engine/pipeline.py、preview_canvas 都判 moving_sticker_enabled）。
        2. 「每次随机轨道」开着 → 每个贴纸的位置那两行置灰：出片时位置会重掷，
           填了也不生效。
        """
        enabled = bool(getattr(self.config, "moving_sticker_enabled", True))
        rolled = enabled and bool(getattr(self.config, "mover_random", True))

        self._folder_row.setEnabled(enabled)
        for key in ("mover_count", "mover_random", "moving_sticker_period"):
            self._rows[key].setEnabled(enabled)
        self._add_button.setEnabled(enabled)
        for box in self._layer_boxes:
            box.setEnabled(enabled)
        for key, row in self._rows.items():
            if not key.startswith("mover_layer_"):
                continue
            field = key.rsplit("_", 1)[-1]
            row.setEnabled(enabled and not (rolled and field in ROLLED_KEYS))

        self._refresh_hint(enabled, rolled)

    def _refresh_hint(self, enabled: bool, rolled: bool) -> None:
        if not enabled:
            self._hint.setText("移动贴纸已关闭，出片时不会加移动贴纸。")
        elif rolled:
            self._hint.setText(
                "「每次随机轨道」开着：下面每行的水平/垂直位置由每次出片重掷，"
                "填了也不生效（置灰那两项）。想固定走位就把它关掉。"
            )
        else:
            # 文本一起清掉，别留一句已经不适用的提示藏在隐藏的标签里。
            self._hint.setText("")
        self._hint.setVisible(bool(self._hint.text()))

    def _update_layer(self, index: int, key: str, value) -> None:
        layers = self._layers()
        if index < len(layers):
            layers[index][key] = value
            self._save_layers(layers)

    def _add_layer(self) -> None:
        self._sync_count(len(self._layers()) + 1)
        # 用不触发信号的 setter 回写滑条：走信号会再进一次 _on_global_changed，
        # 白重建一遍列表（还会把刚加的行按 round-robin 重新分配参数）。
        self._rows["mover_count"].value = self.config.mover_count
        self._rebuild_layers()
        self.preview_changed.emit()

    def _delete_layer(self, index: int) -> None:
        layers = self._layers()
        # 最后一行不给删：0 个移动贴纸用「启用移动贴纸」那个开关表达，
        # 留一行空的反而让「数量」和列表又对不上了。
        if index < len(layers) and len(layers) > 1:
            layers.pop(index)
            self._save_layers(layers)
            self.config.mover_count = len(layers)
            self._rows["mover_count"].value = len(layers)
            self._rebuild_layers()
            self.preview_changed.emit()


def _setattr(obj, key, value):
    try:
        if hasattr(obj, key):
            setattr(obj, key, value)
    except Exception:
        pass
