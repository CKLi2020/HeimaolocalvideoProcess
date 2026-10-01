#!/usr/bin/env python3
"""Reproduce captured kuai_ai encoding and verify stable media features."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


X264_PARAMS = "ref=2:bframes=2:keyint=250:min-keyint=25:no-scenecut=1"
UNKNOWN_TRANSFORMATION = (
    "The tool's transient filter_complex response was deleted before capture. "
    "The worker reproduces its demonstrated 1024x576 yuv444p output structure, "
    "but does not claim pixel-equivalent hidden visual processing."
)


class ProcessingError(RuntimeError):
    pass


def resolve_tool(root: Path, name: str) -> str:
    for candidate in (root / "bin" / name, root / name):
        if candidate.is_file():
            return str(candidate)
    from_path = shutil.which(name)
    if from_path:
        return from_path
    raise ProcessingError(f"Cannot find {name}; put it in bin/ or on PATH.")


def run_capture(command: Sequence[str]) -> str:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode:
        raise ProcessingError(completed.stderr.strip() or "Command failed")
    return completed.stdout


def probe(ffprobe: str, path: Path) -> dict[str, Any]:
    output = run_capture(
        [
            ffprobe,
            "-v", "error",
            "-count_frames",
            "-count_packets",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(path),
        ]
    )
    return json.loads(output)


def first_stream(report: dict[str, Any], codec_type: str) -> dict[str, Any]:
    for stream in report.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    raise ProcessingError(f"Reference has no {codec_type} stream.")


def stable_tags(tags: Any) -> dict[str, Any]:
    if not isinstance(tags, dict):
        return {}
    return {key: value for key, value in tags.items() if key.lower() != "filename"}


def stable_features(report: dict[str, Any]) -> dict[str, Any]:
    format_info = report.get("format", {})
    streams = []
    for stream in report.get("streams", []):
        common = {
            "index": stream.get("index"),
            "codec_name": stream.get("codec_name"),
            "profile": stream.get("profile"),
            "codec_type": stream.get("codec_type"),
            "codec_tag_string": stream.get("codec_tag_string"),
            "time_base": stream.get("time_base"),
            "start_time": stream.get("start_time"),
            "duration": stream.get("duration"),
            "nb_frames": stream.get("nb_frames"),
            "nb_read_frames": stream.get("nb_read_frames"),
            "nb_read_packets": stream.get("nb_read_packets"),
            "disposition": stream.get("disposition"),
            "tags": stable_tags(stream.get("tags")),
        }
        if stream.get("codec_type") == "video":
            common.update(
                {
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "sample_aspect_ratio": stream.get("sample_aspect_ratio"),
                    "display_aspect_ratio": stream.get("display_aspect_ratio"),
                    "pix_fmt": stream.get("pix_fmt"),
                    "level": stream.get("level"),
                    "color_range": stream.get("color_range"),
                    "color_space": stream.get("color_space"),
                    "color_primaries": stream.get("color_primaries"),
                    "color_transfer": stream.get("color_transfer"),
                    "field_order": stream.get("field_order"),
                    "r_frame_rate": stream.get("r_frame_rate"),
                    "avg_frame_rate": stream.get("avg_frame_rate"),
                }
            )
        elif stream.get("codec_type") == "audio":
            common.update(
                {
                    "sample_fmt": stream.get("sample_fmt"),
                    "sample_rate": stream.get("sample_rate"),
                    "channels": stream.get("channels"),
                    "channel_layout": stream.get("channel_layout"),
                }
            )
        streams.append(common)
    return {
        "format": {
            "format_name": format_info.get("format_name"),
            "start_time": format_info.get("start_time"),
            "duration": format_info.get("duration"),
            "tags": stable_tags(format_info.get("tags")),
        },
        "streams": streams,
    }


def differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    if path == "format.duration" or path.endswith(".tags.DURATION"):
        try:
            if path.endswith(".tags.DURATION"):
                expected_parts = expected.split(":")
                actual_parts = actual.split(":")
                expected = int(expected_parts[0]) * 3600 + int(expected_parts[1]) * 60 + float(expected_parts[2])
                actual = int(actual_parts[0]) * 3600 + int(actual_parts[1]) * 60 + float(actual_parts[2])
            return [] if abs(float(expected) - float(actual)) <= 0.0011 else [
                f"{path}: expected {expected!r}, got {actual!r}"
            ]
        except (TypeError, ValueError):
            pass
    if isinstance(expected, dict) and isinstance(actual, dict):
        result: list[str] = []
        for key in expected.keys() | actual.keys():
            child = f"{path}.{key}" if path else key
            if key not in expected:
                result.append(f"{child}: unexpected {actual[key]!r}")
            elif key not in actual:
                result.append(f"{child}: missing (expected {expected[key]!r})")
            else:
                result.extend(differences(expected[key], actual[key], child))
        return result
    if isinstance(expected, list) and isinstance(actual, list):
        result = []
        if len(expected) != len(actual):
            result.append(f"{path}: expected {len(expected)} items, got {len(actual)}")
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            result.extend(differences(expected_item, actual_item, f"{path}[{index}]"))
        return result
    return [] if expected == actual else [f"{path}: expected {expected!r}, got {actual!r}"]


def build_command(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    threads: int,
    video_encoder: str = "libx264",
    encoder_options: Sequence[str] = (),
) -> list[str]:
    gpu = video_encoder != "libx264"
    pixel_format = "yuv420p" if gpu else "yuv444p"
    filter_complex = (
        f"[0:v:0]scale=1024:576,format={pixel_format},split=2[base][duplicate];"
        "[duplicate]trim=start_frame=1[duplicate_tail];"
        "[base][duplicate_tail]interleave[v]"
    )
    command = [
        ffmpeg,
        "-progress", "pipe:2",
        "-y",
        "-hide_banner",
        "-loglevel", "warning",
        "-stats",
        "-stats_period", "0.5",
        "-threads", str(threads),
        "-copyts",
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a:0",
        "-c:v", video_encoder,
    ]
    if gpu:
        command.extend(encoder_options)
    else:
        command.extend([
            "-preset", "veryfast",
            "-crf", "18",
            "-profile:v", "high444",
            "-level:v", "5.2",
            "-refs", "2",
            "-bf", "2",
            "-g", "250",
            "-keyint_min", "25",
            "-sc_threshold", "0",
            "-x264-params", X264_PARAMS,
        ])
    command.extend([
        "-pix_fmt", pixel_format,
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-color_range", "tv",
        "-fps_mode", "passthrough",
        "-threads", str(threads),
        "-c:a", "copy",
        "-avoid_negative_ts", "disabled",
        "-f", "matroska",
        str(output_path),
    ])
    return command


def process(ffmpeg: str, input_path: Path, output_path: Path, threads: int) -> None:
    command = build_command(ffmpeg, input_path, output_path, threads)
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise ProcessingError(f"ffmpeg failed with exit code {completed.returncode}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Reproduce captured kuai_ai stable media features.")
    result.add_argument("input_path", type=Path)
    result.add_argument("output_path", type=Path)
    result.add_argument("--reference", required=True, type=Path, help="kuai_ai output made by the tool")
    result.add_argument("--threads", type=int, default=6)
    result.add_argument("--report", type=Path)
    return result


def main() -> int:
    arguments = parser().parse_args()
    root = Path(__file__).resolve().parents[2]
    input_path = arguments.input_path.expanduser().resolve()
    output_path = arguments.output_path.expanduser().resolve()
    reference_path = arguments.reference.expanduser().resolve()
    try:
        if not input_path.is_file() or not reference_path.is_file():
            raise ProcessingError("Input or reference file does not exist.")
        if arguments.threads < 1:
            raise ProcessingError("--threads must be at least 1.")
        ffmpeg = resolve_tool(root, "ffmpeg.exe")
        ffprobe = resolve_tool(root, "ffprobe.exe")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        process(ffmpeg, input_path, output_path, arguments.threads)
        reference_report = probe(ffprobe, reference_path)
        output_report = probe(ffprobe, output_path)
        expected = stable_features(reference_report)
        actual = stable_features(output_report)
        errors = differences(expected, actual)
        report = {
            "passed": not errors,
            "mode": "kuai_ai",
            "reference": str(reference_path),
            "output": str(output_path),
            "comparison_policy": (
                "Stable ffprobe structure, frame and packet counts; format duration and "
                "Matroska DURATION tags allow 1 ms muxer rounding. Bitrate, size, hashes "
                "and pixels are excluded."
            ),
            "unknown_transformation": UNKNOWN_TRANSFORMATION,
            "errors": errors,
            "expected": expected,
            "actual": actual,
        }
        report_path = arguments.report or output_path.with_suffix(".kuai_ai-report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        print(f"kuai_ai stable features match. Report: {report_path}", file=sys.stderr)
        return 0
    except (OSError, ValueError, KeyError, ProcessingError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())