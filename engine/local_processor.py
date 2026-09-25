"""多平台本地处理模式的后台执行服务。"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from core.build_config import load_config, resolve_path
from core.hardware import detect_gpu_profile
from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, probe_duration, verify_output
from modes import load_modes
from modes.base_mode import VIDEO_EXTS, source_basename, source_stem


class LocalProcessorService:
    def __init__(self):
        self.config = load_config()
        self.ffmpeg = find_ffmpeg(self.config)
        self.ffprobe = find_ffprobe(self.config)
        self.gpu_profile = detect_gpu_profile(self.ffmpeg)
        self.mode_groups = load_modes()
        self.mode_errors = list(getattr(load_modes, "errors", ()))
        self.runner = FFmpegRunner(self.config)
        self._stop = threading.Event()
        self._thread = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    @staticmethod
    def list_videos(path):
        folder = Path(path)
        if not folder.is_dir():
            return []
        return [
            item for item in sorted(folder.iterdir())
            if item.is_file() and item.suffix.lower() in VIDEO_EXTS
        ]

    def start(self, state, mode, files, aux_files, on_log, on_progress, on_done):
        if self.is_running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(state, mode, files, aux_files, on_log, on_progress, on_done),
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        self.runner.stop()

    def _run(self, state, mode, files, aux_files, log, progress, done):
        ok_count = 0
        fail_count = 0
        total = len(files)
        gpu_disabled = False
        output_dir = Path(resolve_path(state["output_dir"]))
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            for index, source in enumerate(files):
                if self._stop.is_set():
                    break
                source = Path(source)
                auxiliary = Path(aux_files[index % len(aux_files)]) if aux_files else None
                final_base = self._output_base(mode, source, output_dir, state)
                temporary_base = final_base + ".part"
                duration = probe_duration(self.config, str(source))
                base_progress = 100.0 * index / total
                progress_span = 100.0 / total

                def task_progress(value, base=base_progress, span=progress_span):
                    progress(base + span * value / 100.0)

                log(f"[{index + 1}/{total}] {source.name}")
                attempts = []
                gpu_requested = bool(state["use_gpu"]) and not gpu_disabled
                if gpu_requested and mode.gpu_supported and mode.has_gpu_command():
                    attempts.extend((True, False))
                else:
                    attempts.append(False)

                code = -1
                for attempt_index, use_gpu in enumerate(attempts):
                    if self._stop.is_set():
                        break
                    if attempt_index and not use_gpu:
                        gpu_disabled = True
                        log("  GPU 处理失败，自动改用 CPU 重试")
                    command, _, error = mode.render(
                        state,
                        str(source),
                        str(auxiliary) if auxiliary else None,
                        use_gpu=use_gpu,
                        out_base=temporary_base,
                    )
                    if error:
                        log("  【失败】" + error)
                        continue
                    self._remove(temporary_base, mode.ext)
                    code = self.runner.run(
                        command,
                        duration=duration,
                        on_log=log,
                        on_progress=task_progress,
                    )
                    if code == 0:
                        break

                if self._stop.is_set():
                    self._remove(temporary_base, mode.ext)
                    break
                if code != 0:
                    fail_count += 1
                    log(f"  【失败】FFmpeg 退出码 {code}")
                    self._remove(temporary_base, mode.ext)
                    continue

                temporary_file = f"{temporary_base}.{mode.ext}"
                valid, message = verify_output(
                    self.config,
                    temporary_file,
                    expected_audio_tracks=getattr(mode, "expected_audio_tracks", None),
                )
                if not valid:
                    fail_count += 1
                    log("  【失败】产物校验未通过：" + message)
                    self._remove(temporary_base, mode.ext)
                    continue

                final_file = f"{final_base}.{mode.ext}"
                os.replace(temporary_file, final_file)
                ok_count += 1
                log(f"  【完成】{Path(final_file).name}（{message}）")
                progress(100.0 * (index + 1) / total)
        except Exception as error:
            fail_count += 1
            log(f"【异常】{type(error).__name__}: {error}")
        finally:
            done(ok_count, fail_count, total, str(output_dir), self._stop.is_set())

    @staticmethod
    def _output_base(mode, source, output_dir, state):
        naming = getattr(mode, "output_naming", None) or state.get("output_naming") or "hash"
        prefix = source_basename(source) if str(naming).lower() == "source" else source_stem(source)
        return str(output_dir / (prefix + str(mode.output_suffix or "")))

    @staticmethod
    def _remove(base, extension):
        try:
            Path(f"{base}.{extension}").unlink(missing_ok=True)
        except OSError:
            pass
