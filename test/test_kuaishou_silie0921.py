"""End-to-end checks for the Kuai Shredder 0921 mode."""

import tempfile
from pathlib import Path

from core.runner import FFmpegRunner, find_ffmpeg, verify_output
from modes import load_modes


def main():
    groups = load_modes()
    modes = {mode.id: mode for items in groups.values() for mode in items}
    assert set(mode.id for mode in groups["快手处理"]) == {
        "kuaishou/motianxinglun",
        "kuaishou/tianbaixinglun",
        "kuaishou/silie0921",
        "kuaishou/binfeng_caishen0923",
    }
    assert [mode.id for mode in groups["快手处理"][:2]] == [
        "kuaishou/motianxinglun",
        "kuaishou/tianbaixinglun",
    ]
    mode = modes["kuaishou/silie0921"]
    assert mode.gpu_supported and mode.has_gpu_command()
    assert mode.ext == "mkv" and not mode.needs_aux

    cfg = {"ffmpeg_path": "bin/ffmpeg.exe", "ffprobe_path": "bin/ffprobe.exe"}
    ffmpeg = find_ffmpeg(cfg)
    assert ffmpeg
    runner = FFmpegRunner(cfg)

    with tempfile.TemporaryDirectory(prefix="kuaishou_silie0921_test_") as folder:
        folder = Path(folder)
        source = folder / "input.mp4"
        make_source = (
            f'"{ffmpeg}" -y -f lavfi -i testsrc2=size=360x640:rate=30 '
            f'-f lavfi -i sine=frequency=440:sample_rate=44100 -t 1 '
            f'-c:v libx264 -pix_fmt yuv420p -c:a aac "{source}"'
        )
        assert runner.run(make_source) == 0, runner.tail(20)

        out_base = folder / "silie0921.part"
        command, is_gpu, error = mode.render(
            {"output_dir": str(folder), "threads": 2},
            str(source),
            use_gpu=False,
            out_base=str(out_base),
        )
        assert not error and not is_gpu, error
        assert runner.run(command) == 0, runner.tail(20)
        ok, message = verify_output(cfg, str(out_base) + ".mkv")
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
                str(source),
                use_gpu=True,
                out_base=str(out_base),
            )
            assert not error and is_gpu, error
            assert encoder in gpu_command
            assert "libx264" not in gpu_command
            assert "x264-params" not in gpu_command
            assert "high444" not in gpu_command

    print("kuaishou silie0921: PASS")


if __name__ == "__main__":
    main()