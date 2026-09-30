"""End-to-end checks for the Xiaohongshu 0924 channels."""

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, probe_media, verify_output
from modes import load_modes


def main():
    groups = load_modes()
    modes = {mode.id: mode for items in groups.values() for mode in items}
    assert {
        mode.id for mode in groups["小红书处理"]
    } == {
        "xiaohongshu/caima0924",
        "xiaohongshu/pianpian0924",
        "xiaohongshu/shuanggui0924",
    }

    mode_ids = (
        "xiaohongshu/caima0924",
        "xiaohongshu/pianpian0924",
        "xiaohongshu/shuanggui0924",
    )
    for mode_id in mode_ids:
        mode = modes[mode_id]
        assert mode.needs_aux is False
        assert mode.gpu_supported is True
        assert mode.has_gpu_command() is True

    ffmpeg = find_ffmpeg({})
    ffprobe = find_ffprobe({})
    assert ffmpeg and ffprobe
    cfg = {"ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe}
    runner = FFmpegRunner(cfg)

    with tempfile.TemporaryDirectory(prefix="xiaohongshu_caima0924_") as folder:
        folder = Path(folder)
        source = folder / "input.mp4"
        make_source = (
            f'"{ffmpeg}" -y -f lavfi -i testsrc2=size=360x640:rate=30 '
            f'-f lavfi -i sine=frequency=440:sample_rate=44100 -t 1 '
            f'-c:v libx264 -pix_fmt yuv420p -c:a aac "{source}"'
        )
        assert runner.run(make_source) == 0, runner.tail(20)

        for mode_id in mode_ids:
            mode = modes[mode_id]
            out_base = folder / (mode_id.rsplit("/", 1)[-1] + ".part")
            render_steps = getattr(mode, "render_steps", None)

            if callable(render_steps):
                _, missing_is_gpu, missing_error = render_steps(
                    {"output_dir": str(folder), "gpu_profile": {"available": False}},
                    str(source), use_gpu=True, out_base=str(out_base),
                )
                commands, is_gpu, error = render_steps(
                    {"output_dir": str(folder), "threads": 2},
                    str(source), use_gpu=False, out_base=str(out_base),
                )
            else:
                _, missing_is_gpu, missing_error = mode.render(
                    {"output_dir": str(folder), "gpu_profile": {"available": False}},
                    str(source), use_gpu=True, out_base=str(out_base),
                )
                command, is_gpu, error = mode.render(
                    {"output_dir": str(folder), "threads": 2},
                    str(source), use_gpu=False, out_base=str(out_base),
                )
                commands = [command]
            assert missing_is_gpu and missing_error
            assert not error and not is_gpu, error
            assert str(out_base) + ".mp4" in commands[-1]
            for command in commands:
                assert runner.run(command) == 0, runner.tail(20)
            ok, message = verify_output(cfg, str(out_base) + ".mp4")
            assert ok, message
            streams = probe_media(cfg, str(out_base) + ".mp4")["streams"]
            assert [stream["codec_name"] for stream in streams] == ["h264", "aac"]

            cleanup_render = getattr(mode, "cleanup_render", None)
            if callable(cleanup_render):
                cleanup_render(out_base)

            for vendor, encoder in (("nvidia", "h264_nvenc"), ("amd", "h264_amf")):
                state = {
                    "output_dir": str(folder),
                    "threads": 2,
                    "gpu_profile": {
                        "available": True,
                        "vendor": vendor,
                        "h264_encoder": encoder,
                    },
                }
                if callable(render_steps):
                    gpu_commands, is_gpu, error = render_steps(
                        state, str(source), use_gpu=True, out_base=str(out_base),
                    )
                else:
                    gpu_command, is_gpu, error = mode.render(
                        state, str(source), use_gpu=True, out_base=str(out_base),
                    )
                    gpu_commands = [gpu_command]
                assert not error and is_gpu, error
                gpu_command = next(command for command in gpu_commands if encoder in command)
                assert "libx264" not in gpu_command
                assert "-crf:v" not in gpu_command
                assert "-refs:v" not in gpu_command
                assert "yuv420p" in gpu_command
                assert "yuv444p" not in gpu_command
                if callable(cleanup_render):
                    cleanup_render(out_base)

    print("xiaohongshu 0924 modes: PASS")


if __name__ == "__main__":
    main()