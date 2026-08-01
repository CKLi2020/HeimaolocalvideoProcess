"""后台工作线程，用于异步执行批量处理。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from config import AppConfig
from engine.pipeline import process_batch, self_test


class BatchWorker:
    """在后台线程中执行批量处理或自检。"""

    def __init__(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        done_callback: Optional[Callable[[bool, str], None]] = None,
    ):
        """
        Args:
            log_callback: 收到日志行
            progress_callback: 进度更新 (current, total)
            done_callback: 任务完成 (success: bool, message: str)
        """
        self._log = log_callback
        self._progress = progress_callback
        self._done = done_callback
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, config: AppConfig, base_dir: Path, channel: str = "hdh") -> None:
        """启动批量处理。"""
        if self.is_running:
            return
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run_batch,
            args=(config, base_dir, channel),
            daemon=True,
        )
        self._thread.start()

    def start_self_test(self, base_dir: Path) -> None:
        """启动环境自检。"""
        if self.is_running:
            return
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run_self_test,
            args=(base_dir,),
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """请求取消当前任务。"""
        self._cancel.set()

    def _run_batch(self, config: AppConfig, base_dir: Path, channel: str) -> None:
        try:
            if channel == "butterfly_ab":
                from engine.butterfly_ab import process_batch as process_butterfly_ab
                ok = process_butterfly_ab(
                    config, base_dir, self._log, self._progress, self._cancel
                )
            else:
                ok = process_batch(
                    config,
                    base_dir,
                    log_callback=self._log,
                    progress_callback=self._progress,
                    cancel_check=lambda: self._cancel.is_set(),
                )
            if self._cancel.is_set():
                self._done and self._done(False, "任务已取消")
            elif ok:
                self._done and self._done(True, "批量处理完成")
            else:
                self._done and self._done(False, "部分或全部任务处理失败")
        except Exception as e:
            self._done and self._done(False, f"处理异常: {e}")

    def _run_self_test(self, base_dir: Path) -> None:
        try:
            ok = self_test(base_dir, log_callback=self._log)
            if ok:
                self._done and self._done(True, "环境自检通过 ✓")
            else:
                self._done and self._done(False, "环境自检失败 ✗")
        except Exception as e:
            self._done and self._done(False, f"自检异常: {e}")
