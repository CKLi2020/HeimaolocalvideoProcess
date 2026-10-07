import io
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import core.runner as runner
from engine import HIDDEN_SUBPROCESS
from modes.kuaishou import mode_kuaishou_binfeng_worker as binfeng
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


@pytest.mark.parametrize("code", [0, 7])
def test_binfeng_probe_is_hidden_and_preserves_errors(monkeypatch, code):
    calls = []

    def run(command, **options):
        calls.append(options)
        return SimpleNamespace(
            returncode=code, stderr="invalid input", stdout='{"streams": []}',
        )

    monkeypatch.setattr(binfeng.subprocess, "run", run)
    if code:
        with pytest.raises(binfeng.ProcessingError, match="invalid input"):
            binfeng.probe("ffprobe.exe", Path("video.mp4"))
    else:
        assert binfeng.probe("ffprobe.exe", Path("video.mp4")) == {"streams": []}
    assert calls[0]["creationflags"] == HIDDEN_SUBPROCESS["creationflags"]


@pytest.mark.parametrize("encoder", ["libx264", "h264_nvenc", "h264_amf"])
def test_binfeng_h264_command_uses_compatible_mp4_tag(encoder):
    reference = {
        "streams": [
            {
                "codec_type": "video",
                "r_frame_rate": "30/1",
                "nb_read_frames": "30",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "time_base": "1/30",
                "codec_tag_string": "hvc1",
            },
            {
                "codec_type": "audio",
                "sample_rate": "48000",
                "channel_layout": "stereo",
                "duration": "1.000000",
                "channels": 2,
            },
        ],
    }
    command = binfeng.build_command(
        "ffmpeg",
        Path("main.mp4"),
        Path("effect.mp4"),
        Path("output.mp4"),
        reference,
        6,
        video_encoder=encoder,
    )
    tag_index = command.index("-tag:v")
    assert command[tag_index + 1] == "avc1"
    assert "hvc1" not in command
