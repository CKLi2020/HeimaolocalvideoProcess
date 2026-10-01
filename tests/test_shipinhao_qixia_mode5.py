from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, verify_output
from modes import load_modes
from modes.shipinhao.mode_qixia_mode5 import MODE


def _state(**updates):
    state = {
        "threads": 2,
        "mode5_lasong": True,
        "mode5_ronghe": True,
        "mode5_daoli": True,
    }
    state.update(updates)
    return state


def test_qixia_mode_is_discovered_and_allows_effect_combinations(tmp_path):
    modes = {mode.id: mode for mode in load_modes()["视频号处理"]}
    assert modes[MODE.id] is MODE
    assert MODE.name == "栖霞"
    assert MODE.needs_aux and MODE.gpu_supported and MODE.has_gpu_command()
    assert MODE.supports_mode5_switches

    source = tmp_path / "main.mp4"
    auxiliary = tmp_path / "effect.mp4"
    source.touch()
    auxiliary.touch()
    command, is_gpu, error = MODE.render(
        {"threads": 2}, str(source), str(auxiliary), use_gpu=False,
        out_base=str(tmp_path / "disabled.part"),
    )
    assert command and not is_gpu and not error
    assert "blend=" not in command and "vflip" not in command
    assert "scale=576:1024" in command and "pad=576:1248:0:112:black" in command

    command, is_gpu, error = MODE.render(
        _state(), str(source), str(auxiliary), use_gpu=False,
        out_base=str(tmp_path / "all-enabled.part"),
    )
    assert command and not is_gpu and not error
    assert "blend=" in command and "vflip" in command
    assert "colorprim=bt709" in command


def test_qixia_cpu_conversion_and_gpu_commands(tmp_path):
    ffmpeg = find_ffmpeg({})
    ffprobe = find_ffprobe({})
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are required for the Qixia integration test")

    source = tmp_path / "main.mp4"
    auxiliary = tmp_path / "effect.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=0.4",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.4",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:size=160x90:rate=30:duration=0.4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(auxiliary),
        ],
        check=True,
    )

    output_base = tmp_path / "qixia.part"
    state = _state()
    command, is_gpu, error = MODE.render(
        state, str(source), str(auxiliary), use_gpu=False, out_base=str(output_base)
    )
    assert not error and not is_gpu
    assert str(auxiliary) in command and "blend=" in command and "vflip" in command
    assert "-x264-params" in command
    assert str(output_base) + ".mp4.encoding.mp4" in command

    runner = FFmpegRunner({"ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe})
    assert runner.run(command, on_log=lambda _line: None) == 0, runner.tail()
    MODE.finalize_render(str(output_base), state)
    MODE.cleanup_render(str(output_base))
    final_path = str(output_base) + ".mp4"
    assert verify_output({"ffprobe_path": ffprobe}, final_path, expected_audio_tracks=1)[0]
    assert not Path(final_path + ".encoding.mp4").exists()

    disabled_output_base = tmp_path / "qixia-disabled.part"
    disabled_state = _state(mode5_lasong=False, mode5_ronghe=False, mode5_daoli=False)
    disabled_command, is_gpu, error = MODE.render(
        disabled_state,
        str(source),
        str(auxiliary),
        use_gpu=False,
        out_base=str(disabled_output_base),
    )
    assert not error and not is_gpu
    assert runner.run(disabled_command, on_log=lambda _line: None) == 0, runner.tail()
    MODE.finalize_render(str(disabled_output_base), disabled_state)
    MODE.cleanup_render(str(disabled_output_base))
    disabled_final_path = str(disabled_output_base) + ".mp4"
    assert verify_output({"ffprobe_path": ffprobe}, disabled_final_path, expected_audio_tracks=1)[0]

    profiles = (
        ("nvidia", "h264_nvenc"),
        ("amd", "h264_amf"),
    )
    for vendor, encoder in profiles:
        gpu_command, is_gpu, error = MODE.render(
            _state(gpu_profile={
                "available": True,
                "vendor": vendor,
                "h264_encoder": encoder,
            }),
            str(source),
            str(auxiliary),
            use_gpu=True,
            out_base=str(tmp_path / f"{vendor}.part"),
        )
        assert not error and is_gpu
        assert encoder in gpu_command
        assert "libx264" not in gpu_command
        assert all(option not in gpu_command for option in ("-x264-params", "-refs", "-bf"))
        assert str(tmp_path / f"{vendor}.part.mp4.encoding.mp4") in gpu_command
