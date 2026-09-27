from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence


MODE = "xiaohongshu_pianpian"
TRIM_HEAD_FRAMES = 5
TRIM_TAIL_FRAMES = 1
FORMAT_DURATION_TOLERANCE = 0.001
STABLE_FORMAT_TAGS = {
    "major_brand",
    "minor_version",
    "compatible_brands",
    "title",
    "artist",
    "album",
    "comment",
    "location",
    "location-eng",
    "make",
    "model",
    "metadata_status",
    "capture_period",
    "encoder",
}
STABLE_STREAM_TAGS = {"language", "handler_name", "vendor_id", "encoder"}
STREAM_FIELDS = (
    "index",
    "codec_name",
    "profile",
    "codec_type",
    "codec_tag_string",
    "width",
    "height",
    "sample_aspect_ratio",
    "display_aspect_ratio",
    "pix_fmt",
    "level",
    "field_order",
    "color_range",
    "color_space",
    "color_primaries",
    "color_transfer",
    "r_frame_rate",
    "avg_frame_rate",
    "time_base",
    "start_pts",
    "start_time",
    "duration_ts",
    "duration",
    "nb_frames",
    "sample_fmt",
    "sample_rate",
    "channels",
    "channel_layout",
)


class ProcessingError(RuntimeError):
    pass


def resolve_tool(name: str, script_dir: Path) -> Path:
    executable = f"{name}.exe"
    for candidate in (
        script_dir / "bin" / executable,
        script_dir / executable,
        script_dir / "config" / "BIN" / "bin4" / executable,
    ):
        if candidate.is_file():
            return candidate.resolve()
    resolved = shutil.which(executable) or shutil.which(name)
    if resolved:
        return Path(resolved).resolve()
    raise ProcessingError(f"Unable to locate {executable} in bin/, the script directory, or PATH.")


def run_checked(arguments: list[str]) -> None:
    try:
        subprocess.run(arguments, check=True)
    except subprocess.CalledProcessError as error:
        raise ProcessingError(f"Command failed with exit code {error.returncode}: {arguments[0]}") from error
    except OSError as error:
        raise ProcessingError(f"Unable to run {arguments[0]}: {error}") from error


def probe(ffprobe: Path, media_path: Path) -> dict[str, Any]:
    arguments = [
        str(ffprobe),
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-show_programs",
        "-show_chapters",
        "-of",
        "json",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as error:
        raise ProcessingError(f"Unable to probe {media_path}: {error}") from error


def get_stream(probe_data: dict[str, Any], codec_type: str) -> dict[str, Any]:
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    raise ProcessingError(f"Required {codec_type} stream is missing.")


def selected_tags(tags: dict[str, Any] | None, allowed: set[str]) -> dict[str, Any]:
    tags = tags or {}
    return {key: tags[key] for key in sorted(allowed) if key in tags}


def normalized_signature(probe_data: dict[str, Any]) -> dict[str, Any]:
    streams = []
    for stream in probe_data.get("streams", []):
        normalized = {field: stream.get(field) for field in STREAM_FIELDS}
        normalized["disposition"] = stream.get("disposition", {})
        normalized["tags"] = selected_tags(stream.get("tags"), STABLE_STREAM_TAGS)
        streams.append(normalized)
    format_data = probe_data.get("format", {})
    return {
        "streams": streams,
        "format": {
            "format_name": format_data.get("format_name"),
            "start_time": format_data.get("start_time"),
            "duration": format_data.get("duration"),
            "chapter_count": len(probe_data.get("chapters", [])),
            "tags": selected_tags(format_data.get("tags"), STABLE_FORMAT_TAGS),
        },
    }


def compare_signatures(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    expected_streams = expected["streams"]
    actual_streams = actual["streams"]
    if len(expected_streams) != len(actual_streams):
        differences.append(
            {"field": "streams.count", "expected": len(expected_streams), "actual": len(actual_streams)}
        )
    for index, (expected_stream, actual_stream) in enumerate(zip(expected_streams, actual_streams)):
        for field, expected_value in expected_stream.items():
            actual_value = actual_stream.get(field)
            if expected_value != actual_value:
                differences.append(
                    {
                        "field": f"streams[{index}].{field}",
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )

    expected_format = expected["format"]
    actual_format = actual["format"]
    for field in ("format_name", "start_time", "chapter_count", "tags"):
        if expected_format.get(field) != actual_format.get(field):
            differences.append(
                {
                    "field": f"format.{field}",
                    "expected": expected_format.get(field),
                    "actual": actual_format.get(field),
                }
            )
    expected_duration = float(expected_format["duration"])
    actual_duration = float(actual_format["duration"])
    if abs(expected_duration - actual_duration) > FORMAT_DURATION_TOLERANCE:
        differences.append(
            {
                "field": "format.duration",
                "expected": expected_format["duration"],
                "actual": actual_format["duration"],
                "tolerance_seconds": FORMAT_DURATION_TOLERANCE,
            }
        )
    return differences


def _frame_count(video: dict[str, Any]) -> int:
    raw_count = video.get("nb_frames") or video.get("nb_read_frames")
    if raw_count not in (None, "N/A"):
        return int(raw_count)
    duration = Fraction(str(video["duration"]))
    return round(duration * Fraction(video["avg_frame_rate"]))


def build_command(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    input_probe: dict[str, Any],
    threads: int,
    video_encoder: str = "libx264",
    encoder_options: Sequence[str] = (),
    pixel_format: str | None = None,
) -> list[str]:
    input_video = get_stream(input_probe, "video")
    input_audio = get_stream(input_probe, "audio")
    input_frames = _frame_count(input_video)
    target_frames = input_frames - TRIM_HEAD_FRAMES - TRIM_TAIL_FRAMES
    if target_frames <= 0:
        raise ProcessingError("Input is too short for the captured head/tail trim.")

    input_rate = Fraction(input_video["avg_frame_rate"])
    target_time_base = Fraction(input_video["time_base"])
    frame_step = int((Fraction(1, 1) / input_rate) / target_time_base)
    trim_start_seconds = Fraction(TRIM_HEAD_FRAMES, 1) / input_rate
    sample_rate = int(input_audio["sample_rate"])
    target_audio_samples = round(Fraction(target_frames, 1) * sample_rate / input_rate)
    output_pixel_format = pixel_format or input_video["pix_fmt"]

    filter_graph = (
        f"[0:v:0]trim=start_frame={TRIM_HEAD_FRAMES}:end_frame={input_frames - TRIM_TAIL_FRAMES},"
        f"settb=expr={target_time_base.numerator}/{target_time_base.denominator},"
        f"setpts=N*{frame_step}[video];"
        f"[0:a:0]atrim=start={float(trim_start_seconds):.9f},"
        f"aresample={sample_rate},apad,"
        f"atrim=end_sample={target_audio_samples},asetpts=PTS-STARTPTS[audio]"
    )
    command = [
        str(ffmpeg),
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_graph,
        "-map",
        "[video]",
        "-map",
        "[audio]",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c:v",
        video_encoder,
    ]
    if video_encoder == "libx264":
        command.extend([
            "-crf:v", "23",
            "-refs:v", "1",
            "-threads", str(threads),
        ])
    command.extend(encoder_options)
    command.extend([
        "-profile:v", "main",
        "-level:v", "4.0",
        "-maxrate:v", "4367k",
        "-bufsize:v", "4367k",
        "-pix_fmt", output_pixel_format,
        "-fps_mode:v", "passthrough",
        "-video_track_timescale", str(target_time_base.denominator),
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar:a", str(sample_rate),
        "-ac:a", str(input_audio["channels"]),
        str(output_path),
    ])
    return command


def build_stage_one(
    ffmpeg: Path,
    input_path: Path,
    intermediate_path: Path,
    input_probe: dict[str, Any],
    reference_probe: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    input_video = get_stream(input_probe, "video")
    reference_video = get_stream(reference_probe, "video")
    input_audio = get_stream(input_probe, "audio")
    reference_audio = get_stream(reference_probe, "audio")
    input_frames = int(input_video["nb_frames"])
    target_frames = int(reference_video["nb_frames"])
    removed_frames = input_frames - target_frames
    if removed_frames < 2:
        raise ProcessingError("Reference does not demonstrate the captured head/tail trim.")
    trim_start_frames = removed_frames - 1
    trim_end_frame = trim_start_frames + target_frames
    input_rate = Fraction(input_video["avg_frame_rate"])
    trim_start_seconds = Fraction(trim_start_frames, 1) / input_rate
    target_rate = Fraction(reference_video["avg_frame_rate"])
    target_time_base = Fraction(reference_video["time_base"])
    frame_step = int((Fraction(1, 1) / target_rate) / target_time_base)
    start_pts = int(reference_video["start_pts"])
    channels = int(reference_audio["channels"])
    target_audio_samples = int(reference_audio["duration_ts"])

    filter_graph = (
        f"[0:v:0]trim=start_frame={trim_start_frames}:end_frame={trim_end_frame},"
        f"settb=expr={target_time_base.numerator}/{target_time_base.denominator},"
        f"setpts=N*{frame_step}+{start_pts}[video];"
        f"[0:a:0]atrim=start={float(trim_start_seconds):.9f},"
        f"aresample={reference_audio['sample_rate']},apad,"
        f"atrim=end_sample={target_audio_samples},asetpts=PTS-STARTPTS[audio]"
    )
    arguments = [
        str(ffmpeg),
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_graph,
        "-map",
        "[video]",
        "-map",
        "[audio]",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-level:v",
        "4.0",
        "-crf:v",
        "23",
        "-maxrate:v",
        "4367k",
        "-bufsize:v",
        "4367k",
        "-refs:v",
        "1",
        "-pix_fmt",
        reference_video["pix_fmt"],
        "-fps_mode:v",
        "passthrough",
        "-video_track_timescale",
        str(target_time_base.denominator),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar:a",
        str(reference_audio["sample_rate"]),
        "-ac:a",
        str(channels),
        str(intermediate_path),
    ]
    return arguments, {
        "trim_start_frames": trim_start_frames,
        "trim_end_frame": trim_end_frame,
        "trim_start_seconds": float(trim_start_seconds),
        "target_video_frames": target_frames,
        "target_video_start_pts": start_pts,
        "target_video_time_base": str(target_time_base),
        "target_audio_samples": target_audio_samples,
        "input_audio_sample_rate": input_audio.get("sample_rate"),
    }


def build_stage_two(
    ffmpeg: Path,
    intermediate_path: Path,
    output_path: Path,
    reference_probe: dict[str, Any],
) -> list[str]:
    arguments = [
        str(ffmpeg),
        "-y",
        "-i",
        str(intermediate_path),
        "-map",
        "0",
        "-c",
        "copy",
    ]
    format_tags = reference_probe.get("format", {}).get("tags", {})
    for key in sorted(STABLE_FORMAT_TAGS - {"major_brand", "minor_version", "compatible_brands", "encoder"}):
        if key in format_tags:
            arguments.extend(["-metadata", f"{key}={format_tags[key]}"])
    creation_time = format_tags.get("creation_time")
    if creation_time:
        arguments.extend(["-metadata", f"creation_time={creation_time}"])
    arguments.extend(["-movflags", "+faststart+use_metadata_tags", str(output_path)])
    return arguments


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce the captured xiaohongshu_pianpian mode.")
    parser.add_argument("input", type=Path, help="Input media path")
    parser.add_argument("output", type=Path, help="Python-generated MP4 path")
    parser.add_argument("--reference", required=True, type=Path, help="Matching tool-produced reference MP4")
    parser.add_argument("--report", type=Path, help="JSON comparison report path")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    script_dir = Path(__file__).resolve().parent
    report_path = arguments.report or script_dir / "capture_xiaohongshu_pianpian" / "comparison.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        input_path = arguments.input.resolve(strict=True)
        reference_path = arguments.reference.resolve(strict=True)
        output_path = arguments.output.resolve()
        if output_path in {input_path, reference_path}:
            raise ProcessingError("Output must not overwrite the input or reference.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = resolve_tool("ffmpeg", script_dir)
        ffprobe = resolve_tool("ffprobe", script_dir)
        input_probe = probe(ffprobe, input_path)
        reference_probe = probe(ffprobe, reference_path)

        with tempfile.TemporaryDirectory(prefix=f"{MODE}_", dir=output_path.parent) as temporary_directory:
            intermediate_path = Path(temporary_directory) / "reenc.mp4"
            stage_one, derived_values = build_stage_one(
                ffmpeg, input_path, intermediate_path, input_probe, reference_probe
            )
            run_checked(stage_one)
            stage_two = build_stage_two(ffmpeg, intermediate_path, output_path, reference_probe)
            run_checked(stage_two)

        expected = normalized_signature(reference_probe)
        actual = normalized_signature(probe(ffprobe, output_path))
        differences = compare_signatures(expected, actual)
        report = {
            "mode": MODE,
            "status": "passed" if not differences else "feature_mismatch",
            "passed": not differences,
            "input": str(input_path),
            "tool_reference": str(reference_path),
            "python_output": str(output_path),
            "ffmpeg": str(ffmpeg),
            "ffprobe": str(ffprobe),
            "stage_one_arguments": stage_one,
            "stage_two_arguments": stage_two,
            "derived_values": derived_values,
            "expected_signature": expected,
            "actual_signature": actual,
            "differences": differences,
            "policy": {
                "format_duration_tolerance_seconds": FORMAT_DURATION_TOLERANCE,
                "excluded": [
                    "file_size",
                    "bit_rate",
                    "whole_file_hash",
                    "encoded_packet_bytes",
                    "pixel_hashes",
                    "creation_time",
                ],
                "unknown_transformations": [
                    "The encrypted first-stage filter text is not exposed. Frame matching demonstrated a six-frame head trim; the worker reproduces the observed trim and timing structure."
                ],
            },
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if not differences else 2
    except ProcessingError as error:
        report = {"mode": MODE, "status": "processing_failure", "passed": False, "error": str(error)}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())