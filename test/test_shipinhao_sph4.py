"""Minimal regression check for the recovered shipinhao/sph4 UI mode."""

import tempfile
from pathlib import Path

from core.runner import FFmpegRunner, find_ffmpeg, probe_media, verify_output
from modes import load_modes


def main():
    groups = load_modes()
    modes = {mode.id: mode for items in groups.values() for mode in items}
    mode = modes["shipinhao/sph4"]
    assert mode.name == "小花猫苍穹通道-2026-9-16更新"
    assert not mode.gpu_supported and mode.expected_audio_tracks == 3
    assert mode.output_naming == "source"

    cfg = {"ffmpeg_path": "bin/ffmpeg.exe", "ffprobe_path": "bin/ffprobe.exe"}
    ffmpeg = find_ffmpeg(cfg)
    assert ffmpeg
    with tempfile.TemporaryDirectory(prefix="sph4_test_") as folder:
        folder = Path(folder)
        source = folder / "input.mp4"
        runner = FFmpegRunner(cfg)
        make = (
            f'"{ffmpeg}" -y -f lavfi -i testsrc2=size=480x854:rate=30 '
            f'-f lavfi -i sine=frequency=440:sample_rate=44100 -t 1 '
            f'-c:v libx264 -pix_fmt yuv420p -c:a aac "{source}"'
        )
        assert runner.run(make) == 0

        out_base = folder / "result.part"
        command, is_gpu, error = mode.render(
            {"output_dir": str(folder), "silent_duration": 3},
            str(source), use_gpu=False, out_base=str(out_base),
        )
        assert not error and not is_gpu
        assert runner.run(command) == 0
        output = folder / "result.part.mp4"
        ok, message = verify_output(cfg, str(output), expected_audio_tracks=3)
        assert ok, message
        info = probe_media(cfg, str(output))
        streams = info["streams"]
        assert [(s["codec_type"], s.get("sample_rate")) for s in streams] == [
            ("video", None), ("audio", "44100"),
            ("audio", "44100"), ("audio", "8000"),
        ]
        assert streams[0]["width"] == 720 and streams[0]["height"] == 1280
        assert streams[0]["avg_frame_rate"] == "30/1"
    print("shipinhao/sph4: PASS")


if __name__ == "__main__":
    main()
