"""声音处理页与 FFmpeg 音轨链回归。可直接 `python tests/test_audio_processing.py`。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import AppConfig
from engine.ffmpeg_builder import build_ffmpeg_command
from engine.pipeline import (
    _adaptive_voice_shift, _estimate_voice_pitch, _pick_playback_rate,
)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    music = root / "音乐"
    music.mkdir()
    fixed = music / "固定.mp3"
    fixed.write_bytes(b"test")

    config = AppConfig(
        audio_bgm_enabled=True,
        audio_bgm_folder=str(music),
        audio_bgm_pick="固定",
        audio_bgm_fixed=fixed.name,
        audio_bgm_volume=15,
        audio_voice_enabled=True,
        audio_voice_mild=False,
        audio_voice_pitch=2,
    )
    config.playback_speed_min = 0.96
    config.playback_speed_max = 1.08
    assert all(0.96 <= _pick_playback_rate(config) <= 1.08 for _ in range(100))

    cmd = build_ffmpeg_command(
        config,
        main_video=root / "main.mp4",
        background_video=None,
        output_path=root / "out.mp4",
        background_audio=fixed,
        main_has_audio=True,
        playback_rate=1.15,
    )
    filters = cmd[cmd.index("-filter_complex") + 1]
    assert "rubberband=pitch=" in filters
    assert "formant=shifted:pitchq=quality" in filters
    assert "volume=0.150[bgm]" in filters
    assert "amix=inputs=2:duration=first" in filters
    assert "setpts=PTS/1.150000" in filters
    assert "atempo=1.150000" in filters
    assert "[playback_audio]" in cmd

    cmd_no_dialogue = build_ffmpeg_command(
        config,
        main_video=root / "silent.mp4",
        background_video=None,
        output_path=root / "silent_out.mp4",
        background_audio=fixed,
        main_has_audio=False,
        playback_rate=0.93,
    )
    silent_filters = cmd_no_dialogue[cmd_no_dialogue.index("-filter_complex") + 1]
    assert "[1:a]" not in silent_filters
    assert "atempo=" in silent_filters  # 背景音乐与画面一起变速
    assert "[playback_audio]" in cmd_no_dialogue

    # 最小端到端：真实生成 1 秒对白 + 背景音乐，确保滤镜链可执行且输出有音轨。
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        main = root / "main_real.mp4"
        bgm = root / "bgm.wav"
        out = root / "out_real.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=64x96:r=10:d=1",
            "-f", "lavfi", "-i", "sine=frequency=110:duration=1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(main),
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
            str(bgm),
        ], check=True, capture_output=True)
        config.resolution = "64x96"
        config.fps = 10
        config.gpu = False
        config.preset = "ultrafast"
        config.sticker_enabled = False
        config.moving_sticker_enabled = False
        real_cmd = build_ffmpeg_command(
            config, main, None, out, background_audio=bgm, main_has_audio=True,
            playback_rate=1.15,
        )
        subprocess.run(real_cmd, check=True, capture_output=True)
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out),
        ], check=True, capture_output=True, text=True)
        assert probe.stdout.strip() == "audio"
        duration = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(out),
        ], check=True, capture_output=True, text=True)
        assert 0.7 < float(duration.stdout) < 1.0, duration.stdout

        detected = _estimate_voice_pitch(main)
        assert detected is not None and 100 <= detected <= 120, detected
        assert _adaptive_voice_shift(110) == 2.0
        assert _adaptive_voice_shift(220) == -2.0
        assert _adaptive_voice_shift(None) == 0.0

        adaptive_cmd = build_ffmpeg_command(
            config, main, None, root / "adaptive.mp4",
            background_audio=bgm, main_has_audio=True, voice_pitch=-2.0,
        )
        adaptive_filters = adaptive_cmd[adaptive_cmd.index("-filter_complex") + 1]
        assert "rubberband=pitch=0.89089872" in adaptive_filters

        config.audio_voice_adaptive = False
        config.audio_voice_enabled = False
        config.audio_voice_mild = True
        mild_out = root / "mild.mp4"
        mild_cmd = build_ffmpeg_command(
            config, main, None, mild_out,
            background_audio=bgm, main_has_audio=True, video_duration=1.0,
        )
        mild_filters = mild_cmd[mild_cmd.index("-filter_complex") + 1]
        for expected in (
            "atempo=", "afftdn=", "acompressor=", "aecho=",
            "stereotools=", "loudnorm=", "alimiter=",
        ):
            assert expected in mild_filters
        assert "rubberband=" not in mild_filters
        segmented_cmd = build_ffmpeg_command(
            config, main, None, root / "segmented.mp4",
            main_has_audio=True, video_duration=25.0,
        )
        segmented_filters = segmented_cmd[
            segmented_cmd.index("-filter_complex") + 1
        ]
        assert "asplit=3" in segmented_filters
        assert "concat=n=3:v=0:a=1" in segmented_filters
        subprocess.run(mild_cmd, check=True, capture_output=True)
        mild_duration = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(mild_out),
        ], check=True, capture_output=True, text=True)
        assert 0.9 < float(mild_duration.stdout) < 1.1, mild_duration.stdout

print("audio processing test: OK")
