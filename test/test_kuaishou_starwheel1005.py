"""End-to-end checks for the two Kuai star-wheel channels."""

import tempfile
from pathlib import Path

from core.runner import FFmpegRunner, find_ffmpeg, verify_output
from engine.native_core import core as native_core
from modes import load_modes


def main():
    groups = load_modes()
    kuaishou = groups["快手处理"]
    assert [mode.id for mode in kuaishou[:2]] == [
        "kuaishou/motianxinglun",
        "kuaishou/tianbaixinglun",
    ]
    modes = {mode.id: mode for mode in kuaishou}
    cases = (
        (modes["kuaishou/motianxinglun"], "星河摩轮1005", 3),
        (modes["kuaishou/tianbaixinglun"], "天穹星澜1005", 3),
    )
    for mode, name, _ in cases:
        assert mode.name == name
        assert not mode.needs_aux
        assert mode.gpu_supported and mode.has_gpu_command()
        assert mode.ext == "mp4"

    motian_plan = native_core.motianxinglun_pipeline_plan(1.25)
    assert motian_plan == native_core.motianxinglun_pipeline_plan(1.25)
    assert motian_plan["image_fps"] == "120"
    tianbai_plan = native_core.tianbaixinglun_pipeline_plan(1.25)
    assert tianbai_plan == native_core.tianbaixinglun_pipeline_plan(1.25)
    assert "all_mode=screen" in tianbai_plan["blend_filter"]
    assert "zoompan=" in tianbai_plan["geometry_filter"]

    cfg = {"ffmpeg_path": "bin/ffmpeg.exe", "ffprobe_path": "bin/ffprobe.exe"}
    ffmpeg = find_ffmpeg(cfg)
    assert ffmpeg
    runner = FFmpegRunner(cfg)

    with tempfile.TemporaryDirectory(prefix="kuaishou_starwheel1005_test_") as folder:
        folder = Path(folder)
        source = folder / "input.mp4"
        make_source = (
            f'"{ffmpeg}" -y -f lavfi -i testsrc2=size=180x320:rate=24 '
            f'-f lavfi -i sine=frequency=440:sample_rate=44100 -t 0.5 '
            f'-c:v libx264 -pix_fmt yuv420p -c:a aac "{source}"'
        )
        assert runner.run(make_source) == 0, runner.tail(20)

        for mode, _, expected_steps in cases:
            stem = mode.id.rsplit("/", 1)[-1]
            out_base = folder / (stem + ".part")
            steps, is_gpu, error = mode.render_steps(
                {"output_dir": str(folder), "threads": 2},
                str(source),
                use_gpu=False,
                out_base=str(out_base),
            )
            assert not error and not is_gpu, error
            assert len(steps) == expected_steps
            assert str(out_base) + ".mp4" in steps[-1]
            for command in steps:
                assert runner.run(command) == 0, runner.tail(30)
            ok, message = verify_output(
                cfg,
                str(out_base) + ".mp4",
                expected_video_tracks=getattr(mode, "expected_video_tracks", 1),
            )
            assert ok, message
            mode.cleanup_render(out_base)
            assert not Path(str(out_base) + f".{stem}_work").exists()

            for vendor, encoder in (("nvidia", "h264_nvenc"), ("amd", "h264_amf")):
                gpu_base = folder / f"{stem}_{vendor}.part"
                gpu_steps, is_gpu, error = mode.render_steps(
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
                    out_base=str(gpu_base),
                )
                assert not error and is_gpu, error
                joined = "\n".join(gpu_steps)
                assert encoder in joined
                assert "libx264" not in joined
                assert "-crf" not in joined
                mode.cleanup_render(gpu_base)

    print("kuaishou star-wheel 1005 modes: PASS")


if __name__ == "__main__":
    main()
