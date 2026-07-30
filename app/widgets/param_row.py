"""通用参数行组件：标签 + 输入控件（支持文本/整数/布尔/下拉）。"""

from __future__ import annotations

import re
from typing import Optional, Union, List

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QWidget,
)
from PySide6.QtCore import Signal, Qt


class ParamRow(QWidget):
    """一行参数：label | widget

    支持类型:
      - "text": QLineEdit
      - "int": QSpinBox (range 0-1000)
      - "int:min-max": QSpinBox with custom range
      - "bool": QCheckBox
      - "combo:opt1,opt2,...": QComboBox
    """

    value_changed = Signal(object)  # 发射当前值

    def __init__(
        self,
        label: str,
        param_type: str = "text",
        initial: Union[str, int, bool] = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        lbl = QLabel(label)
        lbl.setMinimumWidth(120)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl)

        self._type = param_type
        self._widget: QWidget

        if param_type == "bool":
            self._widget = QCheckBox()
            if isinstance(initial, str):
                initial = initial.lower() in ("true", "1", "yes")
            self._widget.setChecked(bool(initial))
            self._widget.toggled.connect(lambda v: self.value_changed.emit(v))
            layout.addWidget(self._widget)
            layout.addStretch()

        elif param_type.startswith("combo:"):
            options = param_type[6:].split(",")
            self._widget = QComboBox()
            self._widget.addItems([o.strip() for o in options])
            if initial and initial in options:
                self._widget.setCurrentText(str(initial))
            self._widget.currentTextChanged.connect(self.value_changed.emit)
            layout.addWidget(self._widget)

        elif param_type == "int" or param_type.startswith(("int:", "slider:")):
            lo, hi = 0, 1000
            if ":" in param_type:
                match = re.fullmatch(r"(-?\d+)-(-?\d+)", param_type.split(":", 1)[1])
                if match:
                    lo, hi = map(int, match.groups())
            self._widget = QSpinBox()
            self._widget.setRange(lo, hi)
            self._widget.setValue(int(initial) if initial else 0)
            if param_type.startswith("slider:"):
                self._widget.setButtonSymbols(QSpinBox.NoButtons)
                self._slider = QSlider(Qt.Horizontal)
                self._slider.setRange(lo, hi)
                self._slider.setValue(self._widget.value())
                self._slider.valueChanged.connect(self._widget.setValue)
                self._widget.valueChanged.connect(self._slider.setValue)
                layout.addWidget(self._slider, 1)
                self._widget.setFixedWidth(68)
            self._widget.valueChanged.connect(self.value_changed.emit)
            layout.addWidget(self._widget)
            layout.addStretch()

        else:  # "text" 或其他
            self._widget = QLineEdit()
            self._widget.setText(str(initial) if initial else "")
            self._widget.textChanged.connect(self.value_changed.emit)
            layout.addWidget(self._widget)

    @property
    def value(self):
        """获取当前值。"""
        if self._type == "bool":
            return self._widget.isChecked()
        elif self._type.startswith("combo:"):
            return self._widget.currentText()
        elif self._type == "int" or self._type.startswith(("int:", "slider:")):
            return self._widget.value()
        else:
            return self._widget.text()

    @value.setter
    def value(self, v) -> None:
        """设置当前值（不触发信号）。"""
        w = self._widget
        if self._type == "bool":
            w.blockSignals(True)
            w.setChecked(bool(v))
            w.blockSignals(False)
        elif self._type.startswith("combo:"):
            w.blockSignals(True)
            if str(v) in [w.itemText(i) for i in range(w.count())]:
                w.setCurrentText(str(v))
            w.blockSignals(False)
        elif self._type == "int" or self._type.startswith(("int:", "slider:")):
            w.blockSignals(True)
            w.setValue(int(v) if v else 0)
            w.blockSignals(False)
        else:
            w.blockSignals(True)
            w.setText(str(v) if v else "")
            w.blockSignals(False)
