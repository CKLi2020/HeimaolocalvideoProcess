"""Coverage for staged local modes and GPU-to-CPU fallback."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_render_mode_runs_requested_output_count(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"source")
    output_dir = tmp_path / "output"
    commands = []
    completed = []
    progress = []
    names = iter(("input栖霞one1", "input栖霞two2", "input栖霞thr3"))
    monkeypatch.setattr(local_processor, "channel_output_stem", lambda *_args: next(names))
    monkeypatch.setattr(local_processor, "probe_duration", lambda *_args: 1.0)
    monkeypatch.setattr(
        local_processor,
        "verify_output",
        lambda _config, path, expected_audio_tracks=None: (Path(path).is_file(), "ok"),
    )

    class Runner:
        def run(self, command, **_kwargs):
            commands.append(command)
            Path(command).write_bytes(b"output")
            return 0

    def render(_state, _main_video, _aux_video, use_gpu, out_base):
        assert not use_gpu
        return out_base + ".mp4", False, ""

    mode = SimpleNamespace(
        id="shipinhao/qixia_mode5", platform="shipinhao", name="栖霞", ext="mp4",
        output_suffix="_qixia_mode5", output_naming="source", gpu_supported=True,
        output_count=lambda state: int(state["copies"]),
        has_gpu_command=lambda: True,
        render=render,
    )
    service = local_processor.LocalProcessorService.__new__(local_processor.LocalProcessorService)
    service.config = {}
    service.runner = Runner()
    service._stop = threading.Event()

    local_processor.LocalProcessorService._run(
        service,
        {"copies": 3, "use_gpu": False, "output_dir": str(output_dir), "output_naming": "source"},
        mode,
        [source],
        [],
        lambda _message: None,
        progress.append,
        lambda *result: completed.append(result),
    )

    assert len(commands) == 3
    assert sorted(path.name for path in output_dir.glob("*.mp4")) == [
        "input栖霞one1.mp4", "input栖霞thr3.mp4", "input栖霞two2.mp4",
    ]
    assert completed[0][:3] == (3, 0, 3)
    assert progress[-1] == 100.0


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
    assert progress_enabled == [True, True, True]
    assert finalized == [str(output_dir / "input_staged.part")]
    assert cleaned == [str(output_dir / "input_staged.part")]
    assert (output_dir / "input_staged.mp4").is_file()
    assert completed[0][:3] == (1, 0, 1)


def test_staged_mode_maps_every_command_into_total_progress(tmp_path):
    reported = []

    class Runner:
        def run(self, _command, on_progress, **_kwargs):
            on_progress(50)
            on_progress(100)
            return 0

    mode = SimpleNamespace(
        gpu_supported=False,
        ext="mp4",
        has_gpu_command=lambda: False,
        render_steps=lambda *_args, **_kwargs: (["stage-1", "stage-2"], False, ""),
    )
    service = local_processor.LocalProcessorService.__new__(local_processor.LocalProcessorService)
    service.runner = Runner()
    service._stop = threading.Event()

    code, fell_back = service._run_commands(
        {"use_gpu": False}, mode, tmp_path / "input.mp4", None,
        str(tmp_path / "output.part"), 10.0, reported.append,
        lambda _message: None, False,
    )

    assert (code, fell_back) == (0, False)
    assert reported == [25.0, 50.0, 75.0, 100.0]


@pytest.mark.parametrize("gpu_requested", [False, True])
def test_finalize_failure_is_logged_and_gpu_retries_cpu(tmp_path, monkeypatch, gpu_requested):
    sources = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    for source in sources:
        source.write_bytes(b"source")
    commands = []
    finalized = []
    cleaned = []
    completed = []
    logs = []
    active = {}

    class Runner:
        def run(self, command, **_kwargs):
            commands.append(command)
            Path(active["base"] + ".mp4").write_bytes(b"encoded")
            return 0

    def render_steps(_state, _main_video, _aux_video, use_gpu, out_base):
        active.update(base=out_base, gpu=use_gpu)
        return ["gpu" if use_gpu else "cpu"], use_gpu, ""

    def finalize_render(out_base, _state):
        finalized.append(active["gpu"])
        if active["gpu"] or not gpu_requested:
            raise ValueError("Unsupported SPS layout")
        Path(out_base + ".mp4").write_bytes(b"compatible")
        return "SPS compatibility applied"

    mode = SimpleNamespace(
        gpu_supported=True, ext="mp4", output_suffix="_compat", output_naming="source",
        has_gpu_command=lambda: True, render_steps=render_steps,
        finalize_render=finalize_render,
        cleanup_render=cleaned.append,
    )
    service = local_processor.LocalProcessorService.__new__(local_processor.LocalProcessorService)
    service.config = {}
    service.runner = Runner()
    service._stop = threading.Event()
    monkeypatch.setattr(local_processor, "probe_duration", lambda *_args: 1.0)
    monkeypatch.setattr(
        local_processor, "verify_output",
        lambda _config, path, **_kwargs: (Path(path).read_bytes() == b"compatible", "ok"),
    )
    output_dir = tmp_path / "output"
    service._run(
        {"use_gpu": gpu_requested, "output_dir": str(output_dir), "output_naming": "source"},
        mode, sources, [], logs.append, lambda _value: None,
        lambda *result: completed.append(result),
    )
    assert len(cleaned) == 2
    assert any("Unsupported SPS layout" in line for line in logs)
    assert not list(output_dir.glob("*.part.mp4"))
    if gpu_requested:
        assert commands == ["gpu", "cpu", "cpu"]
        assert finalized == [True, False, False]
        assert completed[0][:3] == (2, 0, 2)
        assert any("自动改用 CPU" in line for line in logs)
        assert logs.count("  SPS compatibility applied") == 2
    else:
        assert commands == ["cpu", "cpu"]
        assert finalized == [False, False]
        assert completed[0][:3] == (0, 2, 2)
        assert not list(output_dir.glob("*.mp4"))
