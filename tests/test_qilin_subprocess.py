import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from engine import HIDDEN_SUBPROCESS
from modes.douyin import mode_douyin_qilin_worker as worker


@pytest.mark.parametrize("code", [0, 7])
def test_qilin_ffmpeg_commands_are_hidden_and_preserve_errors(monkeypatch, code):
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
    if os.name == "nt":
        assert calls[0]["creationflags"] & subprocess.CREATE_NO_WINDOW


@pytest.mark.parametrize("code", [0, 7])
def test_qilin_probe_is_hidden_and_preserves_results(monkeypatch, code):
    calls = []

    def run(command, **options):
        calls.append(options)
        return SimpleNamespace(
            returncode=code,
            stderr="invalid input",
            stdout='{"streams": []}',
        )

    monkeypatch.setattr(worker.subprocess, "run", run)
    if code:
        with pytest.raises(worker.ProcessingError, match="invalid input"):
            worker.probe(Path("ffprobe.exe"), Path("video.mp4"))
    else:
        assert worker.probe(Path("ffprobe.exe"), Path("video.mp4")) == {"streams": []}
    assert calls[0]["creationflags"] == HIDDEN_SUBPROCESS["creationflags"]
