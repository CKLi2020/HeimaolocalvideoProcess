from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import modes as mode_registry
from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, verify_output
from modes import load_modes
from modes.shipinhao.mode_limeng_1007 import MODE as LIMENG_MODE
from modes.shipinhao.mode_qixia_mode5 import MODE
from modes.shipinhao import mode_shipinghao_mode5_combined_worker as worker


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
    assert not MODE.needs_aux and MODE.gpu_supported and MODE.has_gpu_command()
    assert MODE.capture_output
    assert MODE.supports_copies and MODE.output_count({}) == 1
    assert MODE.output_count({"copies": 999}) == 100
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
    assert command.count("scale=576:1024,pad=576:1248:0:112:black,setsar=1,vflip") == 2
    assert "force_original_aspect_ratio" not in command and "crop=" not in command
    assert "-refs 4" in command and "b-adapt=0" in command


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
            "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
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
    assert str(auxiliary) not in command and "blend=" in command and "vflip" in command
    assert "A*0.50+B*0.50" in command
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
    disabled_probe = json.loads(subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-of", "json", disabled_final_path],
        check=True, capture_output=True, text=True,
    ).stdout)
    disabled_video = disabled_probe["streams"][0]
    assert all(disabled_video.get(field) is None for field in (
        "color_range", "color_space", "color_primaries", "color_transfer",
    ))

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


@pytest.mark.parametrize("opacity", [-1, 101, 50.5, True, "50"])
def test_qixia_invalid_opacity_is_reported(tmp_path, opacity):
    source = tmp_path / "main.mp4"
    source.touch()
    command, is_gpu, error = MODE.render(
        _state(mode5_opacity=opacity), str(source), use_gpu=False,
        out_base=str(tmp_path / "invalid.part"),
    )
    assert not command and not is_gpu
    assert "opacity" in error


@pytest.mark.parametrize("daoli", [False, True])
@pytest.mark.parametrize("lasong", [False, True])
@pytest.mark.parametrize("ronghe", [False, True])
def test_qixia_all_switch_combinations_use_main_input(tmp_path, daoli, lasong, ronghe):
    source = tmp_path / "main.mp4"
    source.touch()
    command, is_gpu, error = MODE.render(
        _state(mode5_daoli=daoli, mode5_lasong=lasong, mode5_ronghe=ronghe,
               mode5_opacity=25),
        str(source), use_gpu=False, out_base=str(tmp_path / "combination.part"),
    )
    assert command and not is_gpu and not error
    assert ("vflip" in command) is daoli
    assert ("colorprim=bt709" in command) is lasong
    assert ("blend=" in command) is ronghe
    if ronghe:
        assert "A*0.25+B*0.75" in command


@pytest.mark.parametrize("packaged", [False, True])
def test_limeng_is_first_and_original_qixia_is_preserved(
    monkeypatch, tmp_path, packaged,
):
    if packaged:
        monkeypatch.setattr(mode_registry, "MODES_DIR", str(tmp_path / "missing-modes"))
    modes = load_modes()["视频号处理"]
    ids = [mode.id for mode in modes]
    assert ids == [
        "shipinhao/limeng_1007",
        "shipinhao/liuying_v15",
        "shipinhao/qixia_mode5",
        "shipinhao/heimao_luoyue",
        "shipinhao/caishen0923",
        "shipinhao/tianjia0923",
    ]
    assert len(ids) == len(set(ids))
    assert modes[0] is LIMENG_MODE
    assert LIMENG_MODE.name == "立梦1007"
    assert LIMENG_MODE.sort_priority < min(
        getattr(mode, "sort_priority", 0) for mode in modes[1:]
    )
    assert modes[2] is MODE
    assert MODE.name == "栖霞"
    assert MODE.id == "shipinhao/qixia_mode5"
    assert MODE.capture_output and MODE.supports_mode5_switches


def test_limeng_forces_only_inversion_and_hides_effect_settings(tmp_path):
    source = tmp_path / "main.mp4"
    source.touch()
    command, is_gpu, error = LIMENG_MODE.render(
        _state(mode5_daoli=False, mode5_lasong=True, mode5_ronghe=True),
        str(source),
        use_gpu=False,
        out_base=str(tmp_path / "limeng.part"),
    )
    assert command and not is_gpu and not error
    assert "vflip" in command
    assert "blend=" not in command
    assert "colorprim=bt709" not in command
    assert not LIMENG_MODE.supports_mode5_switches
    assert not getattr(LIMENG_MODE, "capture_output", False)


@pytest.fixture(scope="module")
def qixia_color_sample(tmp_path_factory):
    ffmpeg = find_ffmpeg({})
    ffprobe = find_ffprobe({})
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are required")
    source = tmp_path_factory.mktemp("qixia-color") / "main.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-y",
        "-f", "lavfi", "-i",
        "color=black:size=160x90:rate=30:duration=0.2,"
        "drawbox=x=0:y=0:w=iw:h=ih/2:color=red:t=fill,"
        "drawbox=x=0:y=ih/2:w=iw:h=ih/2:color=blue:t=fill",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-shortest", str(source),
    ], check=True, capture_output=True)
    return ffmpeg, ffprobe, source


@pytest.mark.parametrize("daoli", [False, True])
@pytest.mark.parametrize("lasong", [False, True])
@pytest.mark.parametrize("ronghe", [False, True])
def test_qixia_cpu_all_combinations_and_actual_flip(
    tmp_path, qixia_color_sample, daoli, lasong, ronghe,
):
    ffmpeg, ffprobe, source = qixia_color_sample
    output_base = str(tmp_path / "combination.part")
    state = _state(mode5_daoli=daoli, mode5_lasong=lasong, mode5_ronghe=ronghe)
    command, is_gpu, error = MODE.render(state, str(source), use_gpu=False, out_base=output_base)
    assert command and not is_gpu and not error
    runner = FFmpegRunner({"ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe})
    assert runner.run(command) == 0, runner.tail()
    MODE.finalize_render(output_base, state)
    MODE.cleanup_render(output_base)
    output = Path(output_base + ".mp4")
    assert verify_output({"ffprobe_path": ffprobe}, str(output), expected_audio_tracks=1)[0]
    video = worker.probe(Path(ffprobe), output)["streams"][0]
    assert (video["width"], video["height"]) == (576, 1248)
    assert ("color_primaries" in video) is lasong
    matrix = any(item["side_data_type"] == "Display Matrix" for item in video.get("side_data_list", []))
    assert matrix is daoli
    decoded = subprocess.run([
        ffmpeg, "-v", "error", "-noautorotate", "-i", str(output),
        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ], check=True, capture_output=True).stdout
    assert len(decoded) == 576 * 1248 * 3
    offset = (368 * 576 + 288) * 3
    red, _green, blue = decoded[offset:offset + 3]
    assert (blue > red + 100) if daoli else (red > blue + 100)
