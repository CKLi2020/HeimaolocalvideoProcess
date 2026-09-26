"""End-to-end checks for the Kuai Binfeng Caishen 0923 mode."""

import tempfile
from pathlib import Path

from core.runner import FFmpegRunner, find_ffmpeg, verify_output
from modes import load_modes


def main():
    groups = load_modes()
    modes = {mode.id: mode for items in groups.values() for mode in items}
    assert "kuaishou/binfeng_caishen0923" in {
        mode.id for mode in groups["快手处理"]
    }
    mode = modes["kuaishou/binfeng_caishen0923"]
    assert mode.needs_aux and mode.gpu_supported and mode.has_gpu_command()

    cfg = {"ffmpeg_path": "bin/ffmpeg.exe", "ffprobe_path": "bin/ffprobe.exe"}
    ffmpeg = find_ffmpeg(cfg)
    assert ffmpeg
    runner = FFmpegRunner(cfg)

    with tempfile.TemporaryDirectory(prefix="kuaishou_binfeng_0923_test_") as folder:
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
            f'-t 1 -c:v libx264 -pix_fmt yuv420p -an "{effect}"'
        )
        assert runner.run(make_source) == 0, runner.tail(20)
        assert runner.run(make_effect) == 0, runner.tail(20)

        out_base = folder / "binfeng_caishen0923.part"
        command, is_gpu, error = mode.render(
            {"output_dir": str(folder), "threads": 2},
            str(source), str(effect), use_gpu=False, out_base=str(out_base),
        )
        assert not error and not is_gpu, error
        assert runner.run(command) == 0, runner.tail(20)
        ok, message = verify_output(cfg, str(out_base) + ".mp4")
        assert ok, message

        for vendor, encoder in (("nvidia", "h264_nvenc"), ("amd", "h264_amf")):
            gpu_command, is_gpu, error = mode.render(
                {
                    "output_dir": str(folder),
                    "threads": 2,
                    "gpu_profile": {
                        "available": True,
                        "vendor": vendor,
                        "h264_encoder": encoder,
                    },
                },
                str(source), str(effect), use_gpu=True, out_base=str(out_base),
            )
            assert not error and is_gpu, error
            assert encoder in gpu_command
            assert "libx264" not in gpu_command
            assert "x264-params" not in gpu_command

    print("kuaishou binfeng caishen 0923: PASS")


if __name__ == "__main__":
    main()