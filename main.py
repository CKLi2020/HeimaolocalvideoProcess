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


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("FlowCut Studio")

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
        config = AppConfig()
        config.to_json(config_path)

    # 显示窗口
    window = MainWindow(config, ROOT)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
