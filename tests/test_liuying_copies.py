from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, verify_output
from engine.local_processor import LocalProcessorService
from engine.native_core import core as native_core
from modes.shipinhao import mode_shipinghao_chuanshanjia_v15_worker as worker
from modes.shipinhao.mode_liuying_v15 import ModeLiuyingV15


@pytest.mark.parametrize("copies", [1, 2])
def test_liuying_independently_processes_each_copy_of_each_input(tmp_path, copies):
    ffmpeg = find_ffmpeg({})
    ffprobe = find_ffprobe({})
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are required")
    source = tmp_path / "main.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=96x160:rate=60:duration=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.5",
            "-shortest", "-map", "1:a:0", "-map", "0:v:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(source),
        ],
        check=True,
    )
    assert [
        stream.get("codec_type")
        for stream in worker.run_probe(Path(ffprobe), source).get("streams", [])
    ] == ["audio", "video"]
    second_source = tmp_path / "second.mp4"
    second_source.write_bytes(source.read_bytes())
    mode = ModeLiuyingV15()
    assert not mode.needs_aux
    service = LocalProcessorService.__new__(LocalProcessorService)
    service.config = {"ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe}
    service.runner = FFmpegRunner(service.config)
    service._stop = threading.Event()
    output_dir = tmp_path / "output"
    completed, logs, progress = [], [], []
    state = {
        "copies": copies,
        "use_gpu": False,
        "threads": 2,
        "output_dir": str(output_dir),
        "random_enhance": True,
        "random_seed": 4000,
    }

    with patch.object(worker, "build_command", wraps=worker.build_command) as builder:
        with patch.object(service.runner, "run", wraps=service.runner.run) as runner:
            service._run(
                state, mode, [source, second_source], [],
                logs.append, progress.append, lambda *result: completed.append(result),
            )
        assert runner.call_count == 2 * copies, logs
        assert builder.call_count == 2 * copies
        assert [call.args[1] for call in builder.call_args_list] == (
            [source] * copies + [second_source] * copies
        )
        assert all(call.args[6] is False for call in builder.call_args_list)
        seeds = [call.args[7] for call in builder.call_args_list]
        assert seeds == [
            native_core.liuying_seed(4000, index) for index in range(2 * copies)
        ]
        commands = [call.args[0] for call in runner.call_args_list]
        assert len(set(commands)) == 2 * copies
        assert all(command.count("perspective=") == 1 for command in commands)

    assert completed[0][:3] == (2 * copies, 0, 2 * copies), logs
    outputs = list(output_dir.glob("*.mp4"))
    assert len(outputs) == 2 * copies
    assert len(list(output_dir.glob("main*.mp4"))) == copies
    assert len(list(output_dir.glob("second*.mp4"))) == copies
    assert all(verify_output(service.config, str(output))[0] for output in outputs)
    video_hashes = []
    for output in outputs:
        result = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(output),
                "-map", "0:v:0", "-f", "framemd5", "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        video_hashes.append(
            tuple(line for line in result.stdout.splitlines() if line and not line.startswith("#"))
        )
    assert len(set(video_hashes)) == len(outputs)
    assert not list(output_dir.glob("*.part*"))
    assert not mode._references
    assert progress[-1] == 100.0


def test_liuying_restores_valid_encode_when_retime_corrupts_output(tmp_path):
    ffmpeg = find_ffmpeg({})
    ffprobe = find_ffprobe({})
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are required")
    source = tmp_path / "main.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=96x160:rate=60:duration=0.2",
            "-f", "lavfi", "-i", "sine=duration=0.2", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
        ],
        check=True,
    )
    base = tmp_path / "result.part"
    encoded = Path(str(base) + ".encoding.mp4")
    encoded.write_bytes(source.read_bytes())
    mode = ModeLiuyingV15()
    mode._references[str(base)] = source

    def corrupt(path, _fps):
        temporary = path.with_name(path.name + ".retime.tmp")
        temporary.write_bytes(b"broken")
        temporary.replace(path)

    with patch.object(worker, "retime_video_track", side_effect=corrupt):
        mode.finalize_render(str(base), {})

    output = Path(str(base) + ".mp4")
    assert verify_output({"ffprobe_path": ffprobe}, output)[0]
    assert not Path(str(base) + ".original.mp4").exists()


def test_liuying_probe_retries_transient_failures_without_console(monkeypatch):
    calls = []
    results = iter([
        SimpleNamespace(returncode=1, stderr="", stdout=""),
        SimpleNamespace(returncode=0, stderr="", stdout='{"streams": []}'),
    ])

    def run(command, **options):
        calls.append(options)
        return next(results)

    monkeypatch.setattr(worker.subprocess, "run", run)
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)
    assert worker.run_probe("ffprobe.exe", Path("output.mp4")) == {"streams": []}
    assert len(calls) == 2
    assert all(
        call["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for call in calls
    )


def test_liuying_probe_reports_all_retry_failures(monkeypatch):
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_options: SimpleNamespace(
            returncode=7, stderr="", stdout="",
        ),
    )
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match=r"after 3 attempts.*exit code 7.*no diagnostic output"):
        worker.run_probe("ffprobe.exe", Path("output.mp4"))
