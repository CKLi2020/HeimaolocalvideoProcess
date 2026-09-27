"""Coverage for staged local modes and GPU-to-CPU fallback."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import engine.local_processor as local_processor


def test_staged_mode_retries_all_cpu_steps_after_gpu_failure(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"source")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    destination = []
    commands = []
    progress_enabled = []
    cleaned = []
    completed = []
    logs = []

    class Runner:
        def run(self, command, **kwargs):
            commands.append(command)
            progress_enabled.append(kwargs["on_progress"] is not None)
            if command == "cpu-stage-2":
                Path(destination[0]).write_bytes(b"output")
            return 1 if command == "gpu-stage-1" else 0

    def render_steps(state, main_video, aux_video, use_gpu, out_base):
        destination[:] = [out_base + ".mp4"]
        steps = ["gpu-stage-1", "gpu-stage-2"] if use_gpu else ["cpu-stage-1", "cpu-stage-2"]
        return steps, use_gpu, ""

    mode = SimpleNamespace(
        gpu_supported=True,
        ext="mp4",
        output_suffix="_staged",
        output_naming="source",
        has_gpu_command=lambda: True,
        render_steps=render_steps,
        cleanup_render=lambda out_base: cleaned.append(out_base),
    )
    service = local_processor.LocalProcessorService.__new__(local_processor.LocalProcessorService)
    service.config = {}
    service.runner = Runner()
    service._stop = threading.Event()
    monkeypatch.setattr(local_processor, "probe_duration", lambda *_args: 1.0)
    monkeypatch.setattr(
        local_processor,
        "verify_output",
        lambda _config, path, expected_audio_tracks=None: (Path(path).is_file(), "ok"),
    )

    local_processor.LocalProcessorService._run(
        service,
        {"use_gpu": True, "output_dir": str(output_dir), "output_naming": "source"},
        mode,
        [source],
        [],
        logs.append,
        lambda _value: None,
        lambda *result: completed.append(result),
    )

    assert commands == ["gpu-stage-1", "cpu-stage-1", "cpu-stage-2"], (completed, logs)
    assert progress_enabled == [False, False, True]
    assert cleaned == [str(output_dir / "input_staged.part")]
    assert (output_dir / "input_staged.mp4").is_file()
    assert completed[0][:3] == (1, 0, 1)
