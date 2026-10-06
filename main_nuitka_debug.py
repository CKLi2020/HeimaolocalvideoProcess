"""Nuitka-only diagnostic entry; never used by protected release builds."""

from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def install_development_cores() -> None:
    from engine import dev_core
    from modes.shipinhao import heimao_luoyue_core

    # The diagnostic build excludes both native extensions at compile time.
    sys.modules["app._flowcut_core"] = dev_core
    sys.modules["app._random_frame_swap_core"] = heimao_luoyue_core


def smoke_test() -> None:
    from engine import dev_core, native_core
    from modes import load_modes
    from modes.shipinhao import heimao_luoyue_core, mode_heimao_luoyue_worker

    assert native_core.core is dev_core
    assert all(hasattr(dev_core, name) for name in native_core._REQUIRED)
    assert mode_heimao_luoyue_worker.filter_graph is heimao_luoyue_core.filter_graph
    groups = load_modes()
    if load_modes.errors:
        raise RuntimeError("\n".join(load_modes.errors))
    assert len(groups) == 8, list(groups)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app.main_window import MainWindow
    from config import AppConfig

    app = QApplication(sys.argv)
    window = MainWindow(AppConfig(), Path(sys.argv[0]).resolve().parent)
    window.show()
    QTimer.singleShot(2000, app.quit)
    result = app.exec()
    if result != 0:
        raise RuntimeError(f"Qt smoke test exited with code {result}")
    print("Diagnostic smoke test: development cores, mode loading and Qt window OK", flush=True)


def main() -> None:
    root = Path(sys.argv[0]).resolve().parent
    os.chdir(root)
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"diagnostic_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
    with log_path.open("w", encoding="utf-8") as log:
        faulthandler.enable(file=log, all_threads=True)
        print("Nuitka diagnostic build: DEVELOPMENT CORES / NO VMPROTECT / NO SPROTECT", flush=True)
        print(f"Diagnostic log: {log_path}", flush=True)
        print(f"Python: {sys.version}\nExecutable: {sys.executable}", file=log, flush=True)
        try:
            install_development_cores()
            if "--diagnostic-smoke-test" in sys.argv:
                smoke_test()
            else:
                from main import main as application_main

                application_main(check_native_host=False)
        except Exception:
            traceback.print_exc(file=log)
            log.flush()
            raise
        finally:
            faulthandler.disable()


if __name__ == "__main__":
    main()
