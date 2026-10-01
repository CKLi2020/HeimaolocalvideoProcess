"""Coverage for staged local modes and GPU-to-CPU fallback."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import engine.local_processor as local_processor


def test_four_platforms_use_source_channel_and_random_token(tmp_path, monkeypatch):
    tokens = iter(("12mp", "a9z0", "skip"))
    monkeypatch.setattr(
        local_processor,
        "channel_output_stem",
        lambda source, channel: f"{source.stem}{channel}{next(tokens)}",
    )
    source = tmp_path / "2.mp4"
    output_dir = tmp_path / "output"
    mode = SimpleNamespace(
        id="douyin/feimao09284", platform="douyin", name="听雪", ext="mp4",
        output_suffix="_ignored",
    )

    assert Path(local_processor.LocalProcessorService._output_base(
        mode, source, output_dir, {}
    )).name == "2听雪12mp"
    assert f"{local_processor.LocalProcessorService._output_base(mode, source, output_dir, {})}.{mode.ext}".endswith(
        "2听雪a9z0.mp4"
    )

    (output_dir / "2听雪skip.mp4").parent.mkdir()
    (output_dir / "2听雪skip.mp4").touch()
    tokens = iter(("skip", "next"))
    monkeypatch.setattr(
        local_processor,
        "channel_output_stem",
        lambda source, channel: f"{source.stem}{channel}{next(tokens)}",
    )
    assert Path(local_processor.LocalProcessorService._output_base(
        mode, source, output_dir, {}
    )).name == "2听雪next"

    mode.ext = "mkv"
    monkeypatch.setattr(
        local_processor,
        "channel_output_stem",
        lambda source, channel: f"{source.stem}{channel}mkv1",
    )
    assert f"{local_processor.LocalProcessorService._output_base(mode, source, output_dir, {})}.{mode.ext}".endswith(
        ".mkv"
    )


def test_other_platforms_keep_existing_output_naming(tmp_path):
    mode = SimpleNamespace(
        id="bili/default", platform="bili", name="默认", ext="mp4",
        output_suffix="_legacy", output_naming="source",
    )
    result = local_processor.LocalProcessorService._output_base(
        mode, tmp_path / "input.mp4", tmp_path / "output", {}
    )
    assert Path(result).name == "input_legacy"


def test_staged_mode_retries_all_cpu_steps_after_gpu_failure(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"source")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    destination = []
    commands = []
    progress_enabled = []
    finalized = []
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

    def finalize_render(out_base, state):
        assert state["use_gpu"] is True
        assert Path(out_base + ".mp4").is_file()
        finalized.append(out_base)

    mode = SimpleNamespace(
        gpu_supported=True,
        ext="mp4",
        output_suffix="_staged",
        output_naming="source",
        has_gpu_command=lambda: True,
        render_steps=render_steps,
        finalize_render=finalize_render,
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
    assert finalized == [str(output_dir / "input_staged.part")]
    assert cleaned == [str(output_dir / "input_staged.part")]
    assert (output_dir / "input_staged.mp4").is_file()
    assert completed[0][:3] == (1, 0, 1)
