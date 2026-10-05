"""End-to-end checks for local Douyin processing modes."""

import tempfile
from pathlib import Path

from core.runner import FFmpegRunner, find_ffmpeg, verify_output
from modes import load_modes


def main():
    groups = load_modes()
    modes = {mode.id: mode for items in groups.values() for mode in items}
    assert set(mode.id for mode in groups["抖音处理"]) == {
        "douyin/feimao09284",
        "douyin/zhandou0921",
        "douyin/tongyao0921",
        "douyin/yunqi_qilin",
    }
    assert groups["抖音处理"][0].id == "douyin/yunqi_qilin"

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

        qilin = modes["douyin/yunqi_qilin"]
        assert qilin.name == "云麒1004"
        assert not qilin.needs_aux and qilin.gpu_supported and qilin.has_gpu_command()
        qilin_source = folder / "qilin_input.mp4"
        make_qilin_source = (
            f'"{ffmpeg}" -y -f lavfi -i testsrc2=size=360x640:rate=30:duration=2 '
            f'-f lavfi -i sine=frequency=520:sample_rate=44100:duration=2 '
            f'-c:v libx264 -pix_fmt yuv420p -c:a aac "{qilin_source}"'
        )
        assert runner.run(make_qilin_source) == 0, runner.tail(20)
        qilin_base = folder / "yunqi.part"
        steps, is_gpu, error = qilin.render_steps(
            {"threads": 2}, str(qilin_source), use_gpu=False, out_base=str(qilin_base)
        )
        assert not error and not is_gpu, error
        assert len(steps) == 6
        assert str(qilin_base) + ".mp4" in steps[-1]
        assert "drawbox=" in steps[1] and "s=198x188" in steps[1]
        assert "drawbox=" in steps[2] and "s=198x188" in steps[2]
        assert "color=c=white" not in steps[1]
        assert "color=c=black:s=256x256" not in steps[2]
        qilin_work = Path(str(qilin_base) + ".yunqi_work")
        first_grid_graph = (qilin_work / "grid_filter.txt").read_text(encoding="utf-8")
        first_blend_graph = (qilin_work / "blend_filter.txt").read_text(encoding="utf-8")
        assert "split=9" in first_grid_graph and "xstack=inputs=20" in first_grid_graph
        assert "anoisesrc=color=pink" in first_blend_graph
        for command in steps:
            assert runner.run(command) == 0, runner.tail(30)
        assert "SPS" in qilin.finalize_render(str(qilin_base), {"use_gpu": False})
        assert (qilin_work / "geo.png").stat().st_size > 500
        assert (qilin_work / "rot.png").stat().st_size > 500
        ok, message = verify_output(cfg, str(qilin_base) + ".mp4")
        assert ok, message
        qilin.cleanup_render(qilin_base)
        assert not Path(str(qilin_base) + ".yunqi_work").exists()

        for vendor, gpu_encoder in (("nvidia", "hevc_nvenc"), ("amd", "hevc_amf")):
            steps, is_gpu, error = qilin.render_steps(
                {
                    "threads": 2,
                    "gpu_profile": {
                        "available": True,
                        "vendor": vendor,
                        "hevc_encoder": gpu_encoder,
                    },
                },
                str(qilin_source),
                use_gpu=True,
                out_base=str(folder / (vendor + ".part")),
            )
            assert not error and is_gpu, error
            blend_command = steps[-2]
            assert gpu_encoder in blend_command
            assert "libx265" not in blend_command
            assert all(option not in blend_command for option in (
                "-x265-params", "-crf", "+ilme", "+ildct",
            ))
            work = Path(str(folder / (vendor + ".part")) + ".yunqi_work")
            assert (work / "grid_filter.txt").read_text(encoding="utf-8") != first_grid_graph
            assert (work / "blend_filter.txt").read_text(encoding="utf-8") != first_blend_graph
            qilin.cleanup_render(str(folder / (vendor + ".part")))

    print("douyin modes: PASS")


if __name__ == "__main__":
    main()