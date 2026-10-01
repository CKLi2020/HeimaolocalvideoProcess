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
        task_callback: Optional[Callable[[dict], None]] = None,
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
        self._task = task_callback
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        config: AppConfig,
        base_dir: Path,
        channel: str = "hdh",
    ) -> None:
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

    def _run_batch(
        self,
        config: AppConfig,
        base_dir: Path,
        channel: str,
    ) -> None:
        try:
            from engine.auth import check
            from engine.ffmpeg_builder import VIDEO_EXTS, list_media

            folder_value = (
                config.ab_main_folder if channel == "butterfly_ab"
                else config.concat_main_folder if channel == "concat"
                else config.cut_main_folder if channel == "cut"
                else config.main_folder
            )
            folder = Path(folder_value)
            if not folder.is_absolute():
                folder = base_dir / folder
            repeat = (
                config.ab_repeat_count if channel == "butterfly_ab"
                else 1 if channel in ("concat", "cut")
                else config.repeat_count
            )

            # 全引擎唯一的授权门禁点。本地模式（engine.auth.local_gate）一律放行；
            # 接入新服务器时在程序入口 set_gate() 一次即可，此处及以下无需改动。
            check(channel, {"main_folder": str(folder), "repeat": repeat})

            if len(list_media(str(folder), VIDEO_EXTS)) * repeat <= 0:
                raise RuntimeError("没有可处理的主视频任务")

            if channel == "concat":
                from engine.concat import process_batch as process_concat
                ok = process_concat(
                    config, base_dir, self._log, self._progress,
                    lambda: self._cancel.is_set(), self._task,
                )
            elif channel == "cut":
                from engine.cut import process_batch as process_cut
                ok = process_cut(
                    config, base_dir, self._log, self._progress,
                    lambda: self._cancel.is_set(), self._task,
                )
            elif channel == "butterfly_ab":
                from engine.butterfly_ab import process_batch as process_butterfly_ab
                ok = process_butterfly_ab(
                    config, base_dir, self._log, self._progress, self._cancel,
                    self._task,
                )
            else:
                ok = process_batch(
                    config,
                    base_dir,
                    log_callback=self._log,
                    progress_callback=self._progress,
                    cancel_check=lambda: self._cancel.is_set(),
                    task_callback=self._task,
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
