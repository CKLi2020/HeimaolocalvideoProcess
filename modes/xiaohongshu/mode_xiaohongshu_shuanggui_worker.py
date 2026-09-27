from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


MODE = "xiaohongshu_shuanggui"
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
    "start_time",
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
    candidates = (
        script_dir / "bin" / executable,
        script_dir / executable,
        script_dir / "config" / "BIN" / "bin4" / executable,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    resolved = shutil.which(executable) or shutil.which(name)
    if resolved:
        return Path(resolved).resolve()
    raise ProcessingError(f"Unable to locate {executable} in bin/, the script directory, or PATH.")


def run_checked(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
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


def build_command(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    threads: int,
    video_encoder: str = "libx264",
    encoder_options: Sequence[str] = (),
    pixel_format: str | None = None,
) -> list[str]:
    output_pixel_format = pixel_format or "yuv444p"
    video_filter = f"format={output_pixel_format},pad=iw:ih+2:0:2:black,fps=120,setdar=16/9"
    command = [
        str(ffmpeg),
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-vf",
        video_filter,
        "-c:v",
        video_encoder,
    ]
    command.extend(encoder_options)
    command.extend([
        "-b:v",
        "15000k",
        "-maxrate:v",
        "18000k",
        "-bufsize:v",
        "16000k",
        "-level:v",
        "4.2",
        "-pix_fmt",
        output_pixel_format,
        "-threads",
        str(threads),
        "-fps_mode:v",
        "cfr",
        "-video_track_timescale",
        "15360",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar:a",
        "48000",
        "-ac:a",
        "2",
        str(output_path),
    ])
    return command


def build_ffmpeg_arguments(ffmpeg: Path, input_path: Path, output_path: Path) -> list[str]:
    return build_command(str(ffmpeg), input_path, output_path, 6)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce the captured xiaohongshu_shuanggui mode.")
    parser.add_argument("input", type=Path, help="Input media path")
    parser.add_argument("output", type=Path, help="Python-generated MP4 path")
    parser.add_argument("--reference", required=True, type=Path, help="Matching tool-produced reference MP4")
    parser.add_argument("--report", type=Path, help="JSON comparison report path")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    script_dir = Path(__file__).resolve().parents[2]
    report_path = arguments.report or script_dir / "capture_xiaohongshu_shuanggui" / "comparison.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        input_path = arguments.input.resolve(strict=True)
        reference_path = arguments.reference.resolve(strict=True)
        output_path = arguments.output.resolve()
        if output_path == input_path or output_path == reference_path:
            raise ProcessingError("Output must not overwrite the input or reference.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = resolve_tool("ffmpeg", script_dir)
        ffprobe = resolve_tool("ffprobe", script_dir)
        command = build_ffmpeg_arguments(ffmpeg, input_path, output_path)
        run_checked(command)

        expected = normalized_signature(probe(ffprobe, reference_path))
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
            "ffmpeg_arguments": command,
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
                ],
                "visual_transform_note": (
                    "The captured private payload was replayable but did not expose its filter expression. "
                    "The worker uses the executable checks that identified a two-row top pad and 120 fps cadence."
                ),
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