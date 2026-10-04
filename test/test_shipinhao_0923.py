"""End-to-end checks for the two Shipinhao 0923 modes."""

import re
import json
import struct
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, verify_output
from modes import load_modes
from modes.shipinhao import mode_shipinghao_chuanshanjia_v15_worker as liuying_worker


def audio_packet_signature(ffprobe, path):
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "a:0", "-show_packets",
            "-show_data_hash", "sha256", "-of", "json", str(path),
        ],
        capture_output=True,
        check=True,
    )
    fields = ("pts", "dts", "duration", "size", "data_hash", "side_data_list")
    return [
        {field: packet[field] for field in fields if field in packet}
        for packet in json.loads(result.stdout)["packets"]
    ]


def assert_movie_timescale(path):
    data = path.read_bytes()
    moov = liuying_worker.find_mp4_child(data, 0, len(data), b"moov")
    assert moov is not None
    mvhd = liuying_worker.find_mp4_child(data, *moov, b"mvhd")
    assert mvhd is not None
    offset = 12 if data[mvhd[0]] == 0 else 20
    assert struct.unpack_from(">I", data, mvhd[0] + offset)[0] == 1000


def video_filter_frame_hashes(ffmpeg, filters):
    result = subprocess.run(
        [
            ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i",
            "testsrc2=size=96x160:rate=60:duration=2",
            "-vf", "select='eq(n,0)',loop=119:1:0,trim=end_frame=120,setpts=N/(60*TB)," + filters,
            "-an", "-enc_time_base:v", "1/60", "-fps_mode", "passthrough",
            "-pix_fmt", "yuv420p", "-f", "framemd5", "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in result.stdout.splitlines()
        if line and not line.startswith("#")
    ]


def assert_one_based_flash_indices(ffmpeg):
    seed = 1234
    command = liuying_worker.build_command(
        ffmpeg, Path("input.mp4"), Path("output.mp4"), 2, random_seed=seed
    )
    filters = command[command.index("-vf") + 1]
    candidate = video_filter_frame_hashes(ffmpeg, filters)
    base = video_filter_frame_hashes(ffmpeg, liuying_worker.VIDEO_FILTER)
    flash_select = "select='eq(mod(n,10),9)*lte(mod(n,60),49)'"
    expected = video_filter_frame_hashes(
        ffmpeg,
        liuying_worker.VIDEO_FILTER + "," + flash_select + "," +
        liuying_worker.perspective_filter(seed),
    )
    flash_slots = [index for index in range(120) if index % 60 in (9, 19, 29, 39, 49)]
    assert len(candidate) == len(base) == 120
    assert len(expected) == len(flash_slots) == 10
    assert [candidate[index] for index in flash_slots] == expected, (
        "Flash transforms must match the captured branch's one-based in counter"
    )
    assert all(candidate[index] == base[index] for index in range(120) if index not in flash_slots)

    preprocess = Mock(stdout=Mock())
    preprocess.wait.return_value = 0
    encoder = Mock()
    encoder.wait.return_value = 0
    with patch.object(liuying_worker.subprocess, "Popen", side_effect=[preprocess, encoder]) as popen:
        liuying_worker.encode(ffmpeg, Path("input.mp4"), Path("output.mp4"), seed)
    standalone = popen.call_args_list[1].args[0]
    standalone_filters = standalone[standalone.index("-vf") + 1]
    assert "ceil(in/12)" in standalone_filters
    assert "ceil(in/12)-1" not in standalone_filters


def main():
    groups = load_modes()
    modes = {mode.id: mode for items in groups.values() for mode in items}
    assert {
        mode.id for mode in groups["视频号处理"]
    } == {
        "shipinhao/heimao_luoyue",
        "shipinhao/qixia_mode5",
        "shipinhao/caishen0923",
        "shipinhao/tianjia0923",
        "shipinhao/liuying_v15",
    }
    assert groups["视频号处理"][0].id == "shipinhao/liuying_v15"

    cfg = {"ffmpeg_path": "bin/ffmpeg.exe", "ffprobe_path": "bin/ffprobe.exe"}
    ffmpeg = find_ffmpeg(cfg)
    ffprobe = find_ffprobe(cfg)
    assert ffmpeg and ffprobe
    assert_one_based_flash_indices(ffmpeg)
    runner = FFmpegRunner(cfg)

    with tempfile.TemporaryDirectory(prefix="shipinhao_0923_test_") as folder:
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

        for mode_id in ("shipinhao/caishen0923", "shipinhao/tianjia0923"):
            mode = modes[mode_id]
            out_base = folder / (mode_id.rsplit("/", 1)[-1] + ".part")
            command, is_gpu, error = mode.render(
                {"output_dir": str(folder), "threads": 2},
                str(source),
                str(effect),
                use_gpu=False,
                out_base=str(out_base),
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
                    str(source),
                    str(effect),
                    use_gpu=True,
                    out_base=str(out_base),
                )
                assert not error and is_gpu, error
                assert encoder in gpu_command
                assert "libx264" not in gpu_command
                assert "x264-params" not in gpu_command

        mode = modes["shipinhao/liuying_v15"]
        assert not mode.needs_aux
        assert mode.gpu_supported
        assert mode.has_gpu_command()
        assert mode.supports_copies
        assert mode.output_count({}) == 1
        assert mode.output_count({"copies": 3}) == 3
        assert mode.output_count({"copies": 999}) == 100

        reference = folder / "reference.mp4"
        make_reference = (
            f'"{ffmpeg}" -y -f lavfi -i testsrc2=size=1080x1920:rate=30 '
            f'-f lavfi -i sine=frequency=660:sample_rate=48000 -t 0.5 '
            f'-c:v libx264 -profile:v high -level:v 4.0 -pix_fmt yuv420p '
            f'-c:a aac -ar 48000 -ac 2 "{reference}"'
        )
        assert runner.run(make_reference) == 0, runner.tail(20)
        reference_probe = liuying_worker.run_probe(ffprobe, reference)
        reference_video = next(
            stream for stream in reference_probe["streams"] if stream["codec_type"] == "video"
        )
        assert reference_video["width"] == 1080
        assert reference_video["height"] == 1920

        out_base = folder / "liuying.part"
        default_command, _, default_error = mode.render(
            {"output_dir": str(folder), "threads": 2, "random_seed": 1234},
            str(source),
            str(reference),
            use_gpu=False,
            out_base=str(out_base),
        )
        assert not default_error, default_error
        assert "eq(mod(in,10),0)" in default_command
        assert "ceil(in/12)" in default_command
        assert "ceil(in/12)-1" not in default_command
        assert "overlay=" not in default_command
        assert default_command.count("perspective=") == 1
        assert "-movie_timescale 1000" in default_command
        default_base = folder / "liuying-default.part"
        default_command, is_gpu, error = mode.render(
            {"output_dir": str(folder), "threads": 2, "random_seed": 1234},
            str(source),
            str(reference),
            use_gpu=False,
            out_base=str(default_base),
        )
        assert not error and not is_gpu, error
        assert runner.run(default_command) == 0, runner.tail(20)
        encoded = Path(str(default_base) + ".encoding.mp4")
        assert_movie_timescale(encoded)
        encoded_audio = audio_packet_signature(ffprobe, encoded)
        mode.finalize_render(str(default_base), {})
        default_output = Path(str(default_base) + ".mp4")
        assert_movie_timescale(default_output)
        assert audio_packet_signature(ffprobe, default_output) == encoded_audio
        mode.cleanup_render(str(default_base))
        ok, message = verify_output(cfg, str(default_base) + ".mp4")
        assert ok, message

        command, is_gpu, error = mode.render(
            {
                "output_dir": str(folder),
                "threads": 2,
                "random_seed": 1234,
                "random_enhance": True,
            },
            str(source),
            str(reference),
            use_gpu=False,
            out_base=str(out_base),
        )
        assert not error and not is_gpu, error
        assert command.count("perspective=") == 1
        assert "ceil(in/12)-1" not in command
        assert "st(5,(PI/180)*(1+4*random(0)))" not in command
        assert command == default_command.replace(str(default_base), str(out_base))
        assert str(out_base) + ".encoding.mp4" in command
        assert runner.run(command) == 0, runner.tail(20)
        mode.finalize_render(str(out_base), {})
        assert_movie_timescale(Path(str(out_base) + ".mp4"))
        assert audio_packet_signature(ffprobe, Path(str(out_base) + ".mp4")) == encoded_audio
        mode.cleanup_render(str(out_base))
        ok, message = verify_output(cfg, str(out_base) + ".mp4")
        assert ok, message
        output_probe = liuying_worker.run_probe(ffprobe, Path(str(out_base) + ".mp4"))
        output_video = next(
            stream for stream in output_probe["streams"] if stream["codec_type"] == "video"
        )
        assert output_video["width"] == liuying_worker.MODE_WIDTH
        assert output_video["height"] == liuying_worker.MODE_HEIGHT
        assert output_video["level"] != reference_video["level"]
        assert output_video["nb_frames"] != reference_video["nb_frames"]

        frame_stats = folder / "toggle_comparison.txt"
        compared = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-i",
                str(folder / "liuying-default.part.mp4"),
                "-i",
                str(out_base) + ".mp4",
                "-filter_complex",
                "[0:v:0][1:v:0]ssim=stats_file=toggle_comparison.txt",
                "-f",
                "null",
                "-",
            ],
            cwd=folder,
            capture_output=True,
            text=True,
            check=False,
        )
        assert compared.returncode == 0, compared.stderr
        unchanged_frames = []
        for line in frame_stats.read_text(encoding="utf-8").splitlines():
            match = re.search(r"\bn:(\d+).*?\bAll:([0-9.]+)", line)
            if not match:
                continue
            frame_index, similarity = int(match.group(1)), float(match.group(2))
            if frame_index % 60 not in (10, 20, 30, 40, 50):
                unchanged_frames.append(similarity)
        assert unchanged_frames and min(unchanged_frames) >= 0.999

        for vendor, encoder in (("nvidia", "h264_nvenc"), ("amd", "h264_amf")):
            gpu_command, is_gpu, error = mode.render(
                {
                    "output_dir": str(folder),
                    "threads": 2,
                    "random_enhance": True,
                    "gpu_profile": {
                        "available": True,
                        "vendor": vendor,
                        "h264_encoder": encoder,
                    },
                },
                str(source),
                str(reference),
                use_gpu=True,
                out_base=str(out_base),
            )
            assert not error and is_gpu, error
            assert encoder in gpu_command
            assert "libx264" not in gpu_command
            assert "-x264-params" not in gpu_command
            assert "perspective=" in gpu_command
            assert gpu_command.count("perspective=") == 1
            assert "ceil(in/12)" in gpu_command
            assert "ceil(in/12)-1" not in gpu_command
            assert "-movie_timescale 1000" in gpu_command
            mode.cleanup_render(str(out_base))

    print("shipinhao 0923 modes: PASS")


if __name__ == "__main__":
    main()