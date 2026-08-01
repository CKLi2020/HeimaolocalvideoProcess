"""后台工作线程，用于异步执行批量处理。"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
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
        license_client=None,
    ) -> None:
        """启动批量处理。"""
        if self.is_running:
            return
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run_batch,
            args=(config, base_dir, channel, license_client),
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
        license_client,
    ) -> None:
        try:
            if license_client is None:
                raise RuntimeError("缺少服务器任务授权")
            from app._flowcut_core import task_claims
            from engine.ffmpeg_builder import VIDEO_EXTS, list_media

            folder_value = (
                config.ab_main_folder if channel == "butterfly_ab"
                else config.main_folder
            )
            folder = Path(folder_value)
            if not folder.is_absolute():
                folder = base_dir / folder
            repeat = (
                config.ab_repeat_count if channel == "butterfly_ab"
                else config.repeat_count
            )
            input_count = len(list_media(str(folder), VIDEO_EXTS)) * repeat
            if input_count <= 0:
                raise RuntimeError("没有可授权的主视频任务")
            engine = "flowcut-ab" if channel == "butterfly_ab" else "flowcut-hdh"
            batch_id = uuid.uuid4().hex
            params_hash = hashlib.sha256(
                json.dumps(
                    config.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            def issue_task_scope():
                token = license_client.task_token(
                    engine, batch_id, input_count, params_hash
                )
                task_claims(
                    token, engine, batch_id,
                    input_count, params_hash, license_client.device_code,
                    license_client.fingerprint,
                )
                return {
                    "token": token,
                    "engine": engine,
                    "batch_id": batch_id,
                    "input_count": input_count,
                    "params_hash": params_hash,
                    "device_code": license_client.device_code,
                    "device_fingerprint": license_client.fingerprint,
                }
            if channel == "butterfly_ab":
                from engine.butterfly_ab import process_batch as process_butterfly_ab
                ok = process_butterfly_ab(
                    config, base_dir, self._log, self._progress, self._cancel,
                    self._task, issue_task_scope,
                )
            else:
                ok = process_batch(
                    config,
                    base_dir,
                    log_callback=self._log,
                    progress_callback=self._progress,
                    cancel_check=lambda: self._cancel.is_set(),
                    task_callback=self._task,
                    task_scope_provider=issue_task_scope,
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
