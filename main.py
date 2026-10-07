"""FlowCut Studio — 视频批量合成工具 入口。"""

from __future__ import annotations

import sys
import os
import faulthandler
import json
import platform
import threading
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(sys.argv[0]).resolve().parent
os.chdir(ROOT)
from version import APP_NAME, APP_VERSION


def _open_startup_log():
    log_dir = Path(os.environ.get("LOCALAPPDATA", ROOT)) / APP_NAME / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"startup-{datetime.now():%Y%m%d-%H%M%S}.log"
    stream = path.open("w", encoding="utf-8", buffering=1)
    old_hook = sys.excepthook

    def report(exc_type, exc_value, exc_tb):
        stream.write("\n=== UNHANDLED EXCEPTION ===\n")
        traceback.print_exception(exc_type, exc_value, exc_tb, file=stream)
        stream.flush()
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None, f"程序异常退出。\n诊断日志：\n{path}", APP_NAME, 0x10,
                )
            except Exception:
                pass
        if not getattr(sys, "frozen", False) and "__compiled__" not in globals():
            old_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = report
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)
    faulthandler.enable(stream, all_threads=True)
    stream.write(
        f"time={datetime.now().isoformat()}\napp={APP_NAME} {APP_VERSION}\n"
        f"exe={sys.executable}\nroot={ROOT}\npython={sys.version}\n"
        f"system={platform.platform()}\nargv={sys.argv!r}\nstartup=begin\n"
    )
    for stale in sorted(log_dir.glob("startup-*.log"))[:-20]:
        try:
            stale.unlink()
        except OSError:
            pass
    return path, stream


CRASH_LOG_PATH, CRASH_LOG = _open_startup_log()
# 注意：不要将 ROOT 加入 sys.path，否则捆绑的 Python 3.12 .pyd
# 会与系统 Python 冲突。系统已通过 pip 安装所需依赖（PySide6,
# faster-whisper 等）。

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont
from PySide6.QtCore import qInstallMessageHandler

from config import AppConfig
from app.main_window import MainWindow


def _qt_message_handler(mode, context, message):
    CRASH_LOG.write(f"qt[{int(mode)}] {message}\n")


qInstallMessageHandler(_qt_message_handler)
CRASH_LOG.write("startup=imports-ok\n")


def _style_native_title_bar(window: MainWindow) -> None:
    if sys.platform != "win32":
        return

    import ctypes

    hwnd = ctypes.c_void_p(int(window.winId()))
    dwm = ctypes.windll.dwmapi
    dark = ctypes.c_int(1)
    if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark)):
        dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))

    for attribute, color in ((35, 0x19101D), (36, 0xFFF1E6), (34, 0x41264C)):
        value = ctypes.c_int(color)
        dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))


def main(*, check_native_host: bool = True) -> None:
    if "--limeng-self-test" in sys.argv:
        from engine.limeng_self_test import run_self_test

        report = {"passed": False}
        try:
            position = sys.argv.index("--limeng-self-test")
            if position + 1 >= len(sys.argv):
                raise ValueError("--limeng-self-test requires an input video path")
            report = run_self_test(ROOT, Path(sys.argv[position + 1]))
        except Exception:
            report["error"] = traceback.format_exc()
        report["app_name"] = APP_NAME
        report["app_version"] = APP_VERSION
        report_dir = ROOT / "capture"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "limeng-self-test.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        sys.exit(0 if report["passed"] else 1)

    if "--native-core-self-test" in sys.argv:
        from engine.core_self_test import run_self_test

        report = {"passed": False}
        try:
            from app import _flowcut_core, _random_frame_swap_core

            report["core_paths"] = {
                "flowcut": _flowcut_core.__file__,
                "random_frame_swap": _random_frame_swap_core.__file__,
            }
            report["host_gates"] = run_self_test(_flowcut_core, _random_frame_swap_core)
            report["passed"] = True
        except Exception:
            report["error"] = traceback.format_exc()
        (ROOT / "native-core-self-test.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        sys.exit(0 if report["passed"] else 1)

    app = QApplication(sys.argv)
    CRASH_LOG.write("startup=qapplication-ok\n")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    if check_native_host and (getattr(sys, "frozen", False) or "__compiled__" in globals()):
        from engine.core_self_test import check_host_gates

        try:
            from app import _flowcut_core, _random_frame_swap_core

            check_host_gates(_flowcut_core, _random_frame_swap_core, require_enabled=True)
        except Exception:
            error = traceback.format_exc()
            logs = ROOT / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "native_core_error.log").write_text(error, encoding="utf-8")
            QMessageBox.critical(
                None, "原生核心检查失败",
                "原生核心无法在当前发布目录中运行。请保留完整的软件目录，"
                "不要单独移动 EXE。\n\n详细原因已保存到 logs/native_core_error.log。\n\n" + error,
            )
            sys.exit(1)

    # 设置默认字体
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)

    # 设置图标
    icon_path = ROOT / "ico" / "xinghuo_logo.ico"
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

    # 显示窗口（本地运行，不再依赖授权服务器）
    window = MainWindow(config, ROOT)
    CRASH_LOG.write("startup=main-window-ok\n")
    window.show()
    _style_native_title_bar(window)

    CRASH_LOG.write("startup=ready\n")
    exit_code = app.exec()
    CRASH_LOG.write(f"exit={exit_code}\n")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
