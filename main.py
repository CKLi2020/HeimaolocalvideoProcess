"""FlowCut Studio — 视频批量合成工具 入口。"""

from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 注意：不要将 ROOT 加入 sys.path，否则捆绑的 Python 3.12 .pyd
# 会与系统 Python 冲突。系统已通过 pip 安装所需依赖（PySide6,
# faster-whisper 等）。

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from config import AppConfig
from app.main_window import MainWindow


def _style_native_title_bar(window: MainWindow) -> None:
    if sys.platform != "win32":
        return

    import ctypes

    hwnd = ctypes.c_void_p(int(window.winId()))
    dwm = ctypes.windll.dwmapi
    dark = ctypes.c_int(1)
    if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark)):
        dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))

    for attribute, color in ((35, 0x1F1007), (36, 0xF6EBE4), (34, 0x3A2113)):
        value = ctypes.c_int(color)
        dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("黑猫苍老师")

    # 设置默认字体
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)

    # 设置图标
    icon_path = ROOT / "ico" / "feng_logo.ico"
    if icon_path.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    # 加载配置
    config_path = ROOT / "config.json"
    if config_path.exists():
        config = AppConfig.from_json(config_path)
    else:
        default_path = ROOT / "配置文件" / "参数预设" / "明花老师.json"
        config = AppConfig.from_json(default_path) if default_path.exists() else AppConfig()
        config.to_json(config_path)
    if config.output_folder == "成品视频":
        config.output_folder = "蒙版成品"
    if config.ab_output_folder == "成品视频":
        config.ab_output_folder = "蝴蝶AB成品"
    config.to_json(config_path)

    # 显示窗口
    window = MainWindow(config, ROOT)
    window.show()
    _style_native_title_bar(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
