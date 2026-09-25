"""文件与批量 标签页。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QFormLayout,
)
from PySide6.QtCore import Signal

from config import AppConfig
from app.widgets.folder_row import FolderRow
from app.widgets.param_row import ParamRow


class FilesPage(QWidget):
    paths_changed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self._rows: dict[str, FolderRow | ParamRow] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(16)

        # ── 文件夹 ──
        # 只有两行可见路径，分组框保持紧凑，把纵向空间留给处理日志。
        folder_group = QGroupBox("文件夹设置")
        folder_form = QFormLayout(folder_group)
        folder_form.setHorizontalSpacing(10)
        folder_form.setVerticalSpacing(18)
        # 两行中间那个空档。给个下限只是兜底：再挤也得有 28px，正常情况下它会把
        # 框里多出来的高度全吃掉（见下面 bottom_pad 的注释）。
        spreader = QWidget()
        spreader.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        spreader.setMinimumHeight(28)
        folder_group.setFixedHeight(230)
        folder_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # 框底也留一点，别让最后一行贴着下边缘。给了上限：富余高度优先灌进中间
        # 那个空档（用户要的是「两行离得更远」），框底只留到看着不挤为止。
        bottom_pad = QWidget()
        bottom_pad.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        bottom_pad.setMinimumHeight(12)
        bottom_pad.setMaximumHeight(28)

        # 「移动贴图文件夹」已挪到右侧的「移动贴纸」页，和移动贴纸的数量、
        # 每个贴纸的轨道参数放在一起；「贴纸文件夹」（不动的贴纸）整行去掉。
        # 字段都还在 config 里继续参与读写往返，只是界面上没有入口了。
        # 这一栏只留整批共用的输入输出目录。
        # 标签为 None 的行是空档：右边放要插进去的那个控件，跨两列、不带标签。
        folders = [
            ("主素材文件夹", "main_folder"),
            ("辅助视频文件夹", "background_folder"),
            (None, spreader),
            ("输出文件夹", "output_folder"),
            (None, bottom_pad),
        ]
        # 这些行整行收起（label 和输入框一起不占位）。行本身仍然建出来并留在
        # self._rows 里：config.json 与预设里的字段继续参与读写往返，不会因为
        # 界面看不见就被静默清掉；要放回来只需把键从这个集合里删掉。
        hidden_rows = {"background_folder"}
        for label, key in folders:
            if label is None:
                folder_form.addRow(key)  # 跨两列的空档行
                continue
            row = FolderRow(placeholder=f"选择{label}...", initial=str(getattr(config, key, "")))
            row.path_changed.connect(lambda v, k=key: self._set_folder(k, v))
            folder_form.addRow(label, row)
            self._rows[key] = row
            if key in hidden_rows:
                folder_form.setRowVisible(row, False)

        root_layout.addWidget(folder_group)

    def _set_folder(self, key: str, value: str) -> None:
        setattr(self.config, key, value)
        self.paths_changed.emit()


def _setattr(obj, key, value):
    """安全设置属性。"""
    try:
        if hasattr(obj, key):
            setattr(obj, key, value)
    except Exception:
        pass
