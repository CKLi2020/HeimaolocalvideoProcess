from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import mode_douyin_feimao_worker as feimao_worker
import mode_xiaohongshu_yanjingshe_worker as yanjingshe_worker
from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, verify_output
from modes import load_modes
from modes.douyin.mode_feimao09284 import MODE as FEIMAO
from modes.xiaohongshu.mode_yanjingshe0928 import MODE as YANJINGSHE


def _platform_modes(platform_title: str) -> dict[str, object]:
    groups = load_modes()
    return {mode.id: mode for mode in groups[platform_title]}


def test_worker_channels_cpu_conversion_and_gpu_commands(tmp_path, monkeypatch):
    ffmpeg = find_ffmpeg({})
    ffprobe = find_ffprobe({})
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are required for worker channel integration")

    source = tmp_path / "main.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=0.25",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.25",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(source),
        ],
        check=True,
    )
    metadata = tmp_path / "metadata.txt"
    metadata.write_text(";FFMETADATA1\ntitle=worker channel test\n", encoding="utf-8")
    monkeypatch.setattr(yanjingshe_worker, "DEFAULT_METADATA_URL", str(metadata))

    capture = tmp_path / "feimao_capture"
    active = capture / "ffargs" / "active"
    active.mkdir(parents=True)
    (capture / "filter_complex.txt").write_text(
        "[0:v]null,setfield=tff[vout];[0:a]anull[aout]", encoding="utf-8"
    )
    response_values = {
        "a001": "ffmetadata",
        "a003": "[vout]",
        "a004": "[aout]",
        "a005": "libx265",
        "a006": "hev1",
        "a007": "yuv420p",
        "a008": "30",
        "a009": "aac",
        "a010": "72k",
        "a011": "2",
        "a012": "44100",
        "a013": "mp4",
    }
    for name, value in response_values.items():
        (active / name).write_text(value, encoding="utf-8")
    monkeypatch.setattr(feimao_worker, "ACTIVE_RUN", capture)
    monkeypatch.setattr(feimao_worker, "RESPONSE_DIR", active)

    loaded_douyin = _platform_modes("抖音处理")
    loaded_xiaohongshu = _platform_modes("小红书处理")
    assert loaded_douyin[FEIMAO.id].needs_aux is False
    assert loaded_xiaohongshu[YANJINGSHE.id].needs_aux is False
    for mode in (FEIMAO, YANJINGSHE):
        assert mode.gpu_supported is True
        assert mode.has_gpu_command() is True

    profiles = (
        ({"available": True, "vendor": "nvidia", "hevc_encoder": "hevc_nvenc", "h264_encoder": "h264_nvenc"},
         {"available": True, "vendor": "nvidia", "hevc_encoder": "hevc_nvenc", "h264_encoder": "h264_nvenc"}),
        ({"available": True, "vendor": "amd", "hevc_encoder": "hevc_amf", "h264_encoder": "h264_amf"},
         {"available": True, "vendor": "amd", "hevc_encoder": "hevc_amf", "h264_encoder": "h264_amf"}),
    )
    for feimao_profile, yanjingshe_profile in profiles:
        feimao_command, is_gpu, error = FEIMAO.render(
            {"gpu_profile": feimao_profile}, str(source), use_gpu=True,
            out_base=str(tmp_path / "gpu_feimao.part"),
        )
        assert not error and is_gpu
        assert feimao_profile["hevc_encoder"] in feimao_command
        assert all(option not in feimao_command for option in ("-crf", "-x265-params", "-field_order", "+ilme+ildct"))
        assert "-sc_threshold" not in feimao_command
        assert "setfield=tff" not in feimao_command
        assert "-tag:v hvc1" in feimao_command
        assert str(tmp_path / "gpu_feimao.part.mp4") in feimao_command

        yanjingshe_command, is_gpu, error = YANJINGSHE.render(
            {"gpu_profile": yanjingshe_profile}, str(source), use_gpu=True,
            out_base=str(tmp_path / "gpu_yanjingshe.part"),
        )
        assert not error and is_gpu
        assert yanjingshe_profile["h264_encoder"] in yanjingshe_command
        assert all(option not in yanjingshe_command for option in ("-bf", "-refs", "-keyint_min"))
        assert "-sc_threshold" not in yanjingshe_command
        assert str(tmp_path / "gpu_yanjingshe.part.mp4") in yanjingshe_command

    runner = FFmpegRunner({"ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe})
    for mode, output_name in ((FEIMAO, "feimao"), (YANJINGSHE, "yanjingshe")):
        temporary_base = tmp_path / (output_name + ".part")
        command, is_gpu, error = mode.render(
            {"metadata_url": str(metadata)}, str(source), use_gpu=False,
            out_base=str(temporary_base),
        )
        assert not error and not is_gpu
        assert str(temporary_base) + ".mp4" in command
        result = runner.run(command, on_log=lambda _line: None)
        assert result == 0, runner.tail()
        assert verify_output(
            {"ffprobe_path": ffprobe}, str(temporary_base) + ".mp4"
        )[0]