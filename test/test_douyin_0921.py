"""End-to-end checks for the two Douyin 0921 modes."""

import tempfile
from pathlib import Path

from core.runner import FFmpegRunner, find_ffmpeg, verify_output
from modes import load_modes


def main():
    groups = load_modes()
    modes = {mode.id: mode for items in groups.values() for mode in items}
    assert set(mode.id for mode in groups["抖音处理"]) == {
        "douyin/zhandou0921",
        "douyin/tongyao0921",
    }

    cfg = {"ffmpeg_path": "bin/ffmpeg.exe", "ffprobe_path": "bin/ffprobe.exe"}
    ffmpeg = find_ffmpeg(cfg)
    assert ffmpeg
    runner = FFmpegRunner(cfg)

    with tempfile.TemporaryDirectory(prefix="douyin_0921_test_") as folder:
        folder = Path(folder)
        source = folder / "input.mp4"
        effect = folder / "effect.mp4"
        make_source = (
            f'"{ffmpeg}" -y -f lavfi -i testsrc2=size=360x640:rate=30 '
            f'-f lavfi -i sine=frequency=440:sample_rate=44100 -t 1 '
            f'-c:v libx264 -pix_fmt yuv420p -c:a aac "{source}"'
        )
        make_effect = (
            f'"{ffmpeg}" -y -f lavfi -i color=blue:size=360x640:rate=30 '
            f'-t 1 -c:v libx264 -pix_fmt yuv420p "{effect}"'
        )
        assert runner.run(make_source) == 0
        assert runner.run(make_effect) == 0

        cases = (
            (modes["douyin/zhandou0921"], None, "nvidia", "hevc_nvenc"),
            (modes["douyin/tongyao0921"], effect, "amd", "hevc_amf"),
        )
        for mode, auxiliary, vendor, gpu_encoder in cases:
            assert mode.gpu_supported and mode.has_gpu_command()
            out_base = folder / (mode.id.rsplit("/", 1)[-1] + ".part")
            command, is_gpu, error = mode.render(
                {"output_dir": str(folder), "threads": 2},
                str(source),
                str(auxiliary) if auxiliary else None,
                use_gpu=False,
                out_base=str(out_base),
            )
            assert not error and not is_gpu, error
            assert runner.run(command) == 0, runner.tail(20)
            ok, message = verify_output(cfg, str(out_base) + ".mp4")
            assert ok, message

            gpu_command, is_gpu, error = mode.render(
                {
                    "output_dir": str(folder),
                    "threads": 2,
                    "gpu_profile": {
                        "available": True,
                        "vendor": vendor,
                        "hevc_encoder": gpu_encoder,
                    },
                },
                str(source),
                str(auxiliary) if auxiliary else None,
                use_gpu=True,
                out_base=str(out_base),
            )
            assert not error and is_gpu, error
            assert gpu_encoder in gpu_command
            assert "libx265" not in gpu_command and "x265-params" not in gpu_command

    print("douyin 0921 modes: PASS")


if __name__ == "__main__":
    main()