"""多平台本地处理模式的后台执行服务。"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from core.build_config import load_config, resolve_path
from core.hardware import detect_gpu_profile
from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, probe_duration, verify_output
from engine.output_naming import CHANNEL_FILENAME_PLATFORMS, channel_output_stem
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
        source_total = len(files)
        output_count = getattr(mode, "output_count", lambda _state: 1)
        copies_per_source = max(1, int(output_count(state)))
        prepare_batch_state = getattr(mode, "prepare_batch_state", None)
        batch_state = prepare_batch_state(state) if callable(prepare_batch_state) else state
        total = source_total * copies_per_source
        gpu_disabled = False
        output_dir = Path(resolve_path(state["output_dir"]))
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            for index, source in enumerate(files):
                if self._stop.is_set():
                    break
                source = Path(source)
                auxiliary = Path(aux_files[index % len(aux_files)]) if aux_files else None
                duration = probe_duration(self.config, str(source))
                base_progress = 100.0 * index / source_total
                progress_span = 100.0 / source_total

                def task_progress(value, base=base_progress, span=progress_span):
                    progress(base + span * value / 100.0)

                log(f"[{index + 1}/{source_total}] {source.name}")
                custom_process = getattr(mode, "process", None)
                if callable(custom_process):
                    final_base = self._output_base(mode, source, output_dir, state)
                    try:
                        outputs = custom_process(
                            state,
                            str(source),
                            final_base,
                            self.ffmpeg,
                            use_gpu=bool(state["use_gpu"]),
                            on_log=log,
                            on_progress=task_progress,
                            should_stop=self._stop.is_set,
                        )
                    except Exception as error:
                        fail_count += copies_per_source
                        log(f"  【失败】{type(error).__name__}: {error}")
                        continue
                    if not outputs:
                        fail_count += copies_per_source
                        log("  【失败】未生成产物")
                        continue
                    ok_count += len(outputs)
                    for output in outputs:
                        log(f"  【完成】{Path(output).name}")
                    if self._stop.is_set():
                        break
                    progress(100.0 * (index + 1) / source_total)
                    continue

                for copy_index in range(copies_per_source):
                    if self._stop.is_set():
                        break
                    final_base = self._output_base(mode, source, output_dir, state)
                    temporary_base = final_base + ".part"
                    task_index = index * copies_per_source + copy_index
                    task_progress_base = 100.0 * task_index / total
                    task_progress_span = 100.0 / total

                    def copy_progress(value, base=task_progress_base, span=task_progress_span):
                        progress(base + span * value / 100.0)

                    state_for_copy = getattr(mode, "state_for_copy", None)
                    task_state = (
                        state_for_copy(batch_state, task_index)
                        if callable(state_for_copy)
                        else batch_state
                    )
                    if copies_per_source > 1:
                        log(f"  [输出 {copy_index + 1}/{copies_per_source}]")
                    code, fell_back = self._run_commands(
                        task_state, mode, source, auxiliary, temporary_base,
                        duration, copy_progress, log, gpu_disabled,
                    )
                    if fell_back:
                        gpu_disabled = True

                    finalize_render = getattr(mode, "finalize_render", None)
                    if code == 0 and not self._stop.is_set() and callable(finalize_render):
                        try:
                            finalize_render(temporary_base, task_state)
                        except Exception as error:
                            code = -1
                            log(f"  【失败】产物封装失败：{type(error).__name__}: {error}")

                    cleanup_render = getattr(mode, "cleanup_render", None)
                    if callable(cleanup_render):
                        cleanup_render(temporary_base)

                    if self._stop.is_set():
                        self._remove(temporary_base, mode.ext)
                        break
                    if code != 0:
                        fail_count += 1
                        log(f"  【失败】处理退出码 {code}")
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
                    progress(100.0 * (task_index + 1) / total)
        except Exception as error:
            fail_count += 1
            log(f"【异常】{type(error).__name__}: {error}")
        finally:
            done(ok_count, fail_count, total, str(output_dir), self._stop.is_set())

    def _run_commands(self, state, mode, source, auxiliary, temporary_base,
                      duration, task_progress, log, gpu_disabled):
        attempts = []
        gpu_requested = bool(state["use_gpu"]) and not gpu_disabled
        if gpu_requested and mode.gpu_supported and mode.has_gpu_command():
            attempts.extend((True, False))
        else:
            attempts.append(False)

        code = -1
        fell_back = False
        for attempt_index, use_gpu in enumerate(attempts):
            if self._stop.is_set():
                break
            if attempt_index and not use_gpu:
                fell_back = True
                log("  GPU 处理失败，自动改用 CPU 重试")
            render_steps = getattr(mode, "render_steps", None)
            if callable(render_steps):
                commands, _, error = render_steps(
                    state,
                    str(source),
                    str(auxiliary) if auxiliary else None,
                    use_gpu=use_gpu,
                    out_base=temporary_base,
                )
            else:
                command, _, error = mode.render(
                    state,
                    str(source),
                    str(auxiliary) if auxiliary else None,
                    use_gpu=use_gpu,
                    out_base=temporary_base,
                )
                commands = [command] if command else []
            if error:
                log("  【失败】" + error)
                continue
            self._remove(temporary_base, mode.ext)
            code = -1
            for command_index, command in enumerate(commands):
                code = self.runner.run(
                    command,
                    duration=duration,
                    on_log=log,
                    on_progress=(task_progress if command_index == len(commands) - 1 else None),
                )
                if code != 0 or self._stop.is_set():
                    break
            if code == 0:
                break
        return code, fell_back

    @staticmethod
    def _output_base(mode, source, output_dir, state):
        platform = str(getattr(mode, "id", "") or "").partition("/")[0]
        platform = platform or str(getattr(mode, "platform", "") or "")
        if platform in CHANNEL_FILENAME_PLATFORMS:
            extension = str(getattr(mode, "ext", "mp4") or "mp4")
            while True:
                base = output_dir / channel_output_stem(source, getattr(mode, "name", ""))
                if not Path(f"{base}.{extension}").exists() and not Path(f"{base}.part.{extension}").exists():
                    return str(base)
        naming = getattr(mode, "output_naming", None) or state.get("output_naming") or "hash"
        prefix = source_basename(source) if str(naming).lower() == "source" else source_stem(source)
        return str(output_dir / (prefix + str(mode.output_suffix or "")))

    @staticmethod
    def _remove(base, extension):
        try:
            Path(f"{base}.{extension}").unlink(missing_ok=True)
        except OSError:
            pass
