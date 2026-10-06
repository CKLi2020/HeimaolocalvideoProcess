import io
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import core.runner as runner
from engine import HIDDEN_SUBPROCESS
from modes.kuaishou import mode_kuaishou_motianxinglun_worker as motian
from modes.kuaishou import mode_kuaishou_tianbaixinglun_worker as tian


def test_staged_ffmpeg_has_no_console_without_changing_logs_or_exit_code(monkeypatch):
    calls = []

    def popen(command, **options):
        calls.append(options)
        return SimpleNamespace(
            stdout=io.StringIO("encoder failure\n"), wait=lambda: 7,
        )

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    logs = []
    instance = runner.FFmpegRunner()
    assert instance.run("ffmpeg.exe -version", on_log=logs.append) == 7
    flags = calls[0]["creationflags"]
    assert flags == runner._CREATE_NEW_PROCESS_GROUP | runner._CREATE_NO_WINDOW
    if runner.os.name == "nt":
        assert flags & subprocess.CREATE_NO_WINDOW
        assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert logs[-1] == "encoder failure"
    assert instance.tail() == "encoder failure"


@pytest.mark.parametrize("code", [0, 7])
@pytest.mark.parametrize("worker", [motian, tian], ids=["motianxinglun", "tianbaixinglun"])
def test_worker_commands_are_hidden_and_errors_remain_visible(monkeypatch, code, worker):
    calls = []

    def run(command, **options):
        calls.append(options)
        return SimpleNamespace(returncode=code, stderr="encoding failed", stdout="")

    monkeypatch.setattr(worker.subprocess, "run", run)
    if code:
        with pytest.raises(worker.ProcessingError, match="encoding failed"):
            worker.run_command(["ffmpeg.exe", "-version"])
    else:
        worker.run_command(["ffmpeg.exe", "-version"])
    assert calls[0]["creationflags"] == HIDDEN_SUBPROCESS["creationflags"]


@pytest.mark.parametrize("code", [0, 7])
@pytest.mark.parametrize("worker", [motian, tian], ids=["motianxinglun", "tianbaixinglun"])
def test_worker_probe_is_hidden_and_preserves_results(monkeypatch, code, worker):
    calls = []

    def run(command, **options):
        calls.append(options)
        return SimpleNamespace(
            returncode=code, stderr="invalid input", stdout='{"streams": []}',
        )

    monkeypatch.setattr(worker.subprocess, "run", run)
    if code:
        with pytest.raises(worker.ProcessingError, match="invalid input"):
            worker.probe(Path("ffprobe.exe"), Path("video.mp4"))
    else:
        assert worker.probe(Path("ffprobe.exe"), Path("video.mp4")) == {"streams": []}
    assert calls[0]["creationflags"] == HIDDEN_SUBPROCESS["creationflags"]
