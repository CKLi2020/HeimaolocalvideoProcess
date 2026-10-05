from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.native_core import core as _native_core


SCRIPT_DIR = Path(__file__).resolve().parent
CAPTURE_RUN = (
    SCRIPT_DIR
    / "capture_kuaishou_tianbaixinglun"
    / "run_20261005_135000_9c47c669"
)
ARTIFACTS_DIR = CAPTURE_RUN / "command_artifacts"
CAPTURED_GEOMETRY_FRAME = SCRIPT_DIR / "tianbaixinglun_artifacts" / "geometry_frame.png"
CAPTURED_FILTER_SCRIPT = (
    ARTIFACTS_DIR / "watch_639267762313404630_80b56344_av_hwframe_69bbcaeddd.tmp"
)

STREAM_FIELDS = (
    "index",
    "codec_type",
    "codec_name",
    "profile",
    "codec_tag_string",
    "width",
    "height",
    "coded_width",
    "coded_height",
    "level",
    "has_b_frames",
    "sample_aspect_ratio",
    "display_aspect_ratio",
    "pix_fmt",
    "field_order",
    "color_range",
    "color_space",
    "color_primaries",
    "color_transfer",
    "r_frame_rate",
    "avg_frame_rate",
    "time_base",
    "start_time",
    "duration_ts",
    "duration",
    "nb_frames",
    "sample_fmt",
    "sample_rate",
    "channels",
    "channel_layout",
)
STREAM_TAGS = ("language", "handler_name", "vendor_id", "encoder")
FORMAT_TAGS = ("major_brand", "minor_version", "compatible_brands")


class ProcessingError(Exception):
    pass


def resolve_tool(name: str) -> Path:
    candidates = (
        SCRIPT_DIR / "bin" / name,
        SCRIPT_DIR / name,
        SCRIPT_DIR / "config" / "bin" / "bin4" / name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    raise ProcessingError(f"Cannot find {name} in bin/, beside the worker, or on PATH.")


def run_command(arguments: list[str]) -> None:
    result = subprocess.run(
        arguments,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise ProcessingError(
            f"Command failed with exit code {result.returncode}: "
            f"{subprocess.list2cmdline(arguments)}\n{details}"
        )


def probe(ffprobe: Path, media_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
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
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ProcessingError(
            f"ffprobe failed for {media_path} with exit code {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def stable_tags(tags: dict[str, Any] | None, allowed: tuple[str, ...]) -> dict[str, Any]:
    if not tags:
        return {}
    return {key: tags[key] for key in allowed if key in tags}


def signature(data: dict[str, Any]) -> dict[str, Any]:
    streams = []
    for stream in data.get("streams", []):
        item = {field: stream.get(field) for field in STREAM_FIELDS}
        item["disposition"] = stream.get("disposition", {})
        item["tags"] = stable_tags(stream.get("tags"), STREAM_TAGS)
        streams.append(item)

    chapters = []
    for chapter in data.get("chapters", []):
        chapters.append(
            {
                "id": chapter.get("id"),
                "time_base": chapter.get("time_base"),
                "start": chapter.get("start"),
                "start_time": chapter.get("start_time"),
                "end": chapter.get("end"),
                "end_time": chapter.get("end_time"),
                "tags": stable_tags(chapter.get("tags"), ("title", "language")),
            }
        )

    container = data.get("format", {})
    return {
        "streams": streams,
        "programs": len(data.get("programs", [])),
        "chapters": chapters,
        "format": {
            "format_name": container.get("format_name"),
            "start_time": container.get("start_time"),
            "duration": container.get("duration"),
            "tags": stable_tags(container.get("tags"), FORMAT_TAGS),
        },
    }


def _differences(
    expected: Any, actual: Any, path: str = "$", skip_format_duration: bool = True
) -> list[dict[str, Any]]:
    if path == "$.format.duration" and skip_format_duration:
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}"
            if key not in expected:
                changes.append({"path": child, "expected": "<missing>", "actual": actual[key]})
            elif key not in actual:
                changes.append({"path": child, "expected": expected[key], "actual": "<missing>"})
            else:
                changes.extend(_differences(expected[key], actual[key], child, skip_format_duration))
        return changes
    if isinstance(expected, list) and isinstance(actual, list):
        changes = []
        if len(expected) != len(actual):
            changes.append(
                {"path": f"{path}.length", "expected": len(expected), "actual": len(actual)}
            )
        for index, (left, right) in enumerate(zip(expected, actual)):
            changes.extend(_differences(left, right, f"{path}[{index}]", skip_format_duration))
        return changes
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual}]
    return []


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    changes = _differences(expected, actual)
    expected_streams = expected.get("streams", [])
    actual_streams = actual.get("streams", [])
    stream_counts_match = len(expected_streams) == len(actual_streams)
    stream_timing_matches = stream_counts_match and all(
        left.get("duration") == right.get("duration")
        and left.get("duration_ts") == right.get("duration_ts")
        and left.get("nb_frames") == right.get("nb_frames")
        for left, right in zip(expected_streams, actual_streams)
    )
    expected_duration = expected.get("format", {}).get("duration")
    actual_duration = actual.get("format", {}).get("duration")
    try:
        duration_delta = abs(float(expected_duration) - float(actual_duration))
    except (TypeError, ValueError):
        duration_delta = float("inf")
    if duration_delta > 0.001 or not stream_timing_matches:
        changes.append(
            {
                "path": "$.format.duration",
                "expected": expected_duration,
                "actual": actual_duration,
                "tolerance_seconds": 0.001 if stream_timing_matches else 0,
            }
        )
    return changes


def _video_options(
    video_encoder: str,
    encoder_options: tuple[str, ...],
    preset: str,
    crf: str,
) -> list[str]:
    if video_encoder == "libx264":
        return ["-preset", preset, "-crf", crf]
    return list(encoder_options)


def build_commands(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    work: Path,
    geometry_frame: Path,
    duration: float,
    threads: int,
    video_encoder: str = "libx264",
    encoder_options: tuple[str, ...] = (),
) -> list[list[str]]:
    plan = _native_core.tianbaixinglun_pipeline_plan(duration)
    work.mkdir(parents=True, exist_ok=True)
    main_video = work / "main_60fps.mp4"
    geometry_video = work / "geometry_loop.mp4"
    filter_script = work / "blend_filter.txt"
    filter_script.write_text(plan["blend_filter"], encoding="utf-8")

    main_command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(input_path), "-vf", plan["main_filter"], "-map_metadata", "-1",
        "-c:v", video_encoder,
        *_video_options(video_encoder, encoder_options, "fast", "18"),
        "-pix_fmt", "yuv420p", "-r", "60", "-fps_mode", "cfr",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-threads", str(threads), str(main_video),
    ]
    geometry_command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-loop", "1", "-i", str(geometry_frame), "-t", "8.000",
        "-vf", plan["geometry_filter"], "-c:v", video_encoder,
        *_video_options(video_encoder, encoder_options, "fast", "20"),
        "-pix_fmt", "yuv420p", "-b:v", "3500k", "-r", "60",
        "-fps_mode", "cfr", "-an", "-threads", str(threads),
        str(geometry_video),
    ]
    blend_command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(main_video), "-stream_loop", "-1", "-i", str(geometry_video),
        "-/filter_complex", str(filter_script), "-map", "[v]", "-map", "0:a?",
        "-t", plan["duration"], "-c:v", video_encoder,
        *_video_options(video_encoder, encoder_options, "fast", "20"),
        "-pix_fmt", "yuv420p", "-b:v", "8M", "-maxrate", "12M",
        "-bufsize", "16M", "-r", "60", "-fps_mode", "cfr",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-threads", str(threads), str(output_path),
    ]
    return [main_command, geometry_command, blend_command]


def produce(
    ffmpeg: Path,
    ffprobe: Path,
    input_path: Path,
    output_path: Path,
    geometry_frame: Path,
) -> dict[str, Any]:
    if not input_path.is_file():
        raise ProcessingError(f"Input file does not exist: {input_path}")
    if not geometry_frame.is_file():
        raise ProcessingError(f"Geometry frame does not exist: {geometry_frame}")
    if output_path.exists():
        raise ProcessingError(f"Refusing to overwrite existing output: {output_path}")
    if input_path.resolve() == output_path.resolve():
        raise ProcessingError("Input and output paths must be different.")

    source_probe = probe(ffprobe, input_path)
    if not any(stream.get("codec_type") == "video" for stream in source_probe.get("streams", [])):
        raise ProcessingError("The input has no video stream.")
    duration_value = source_probe.get("format", {}).get("duration")
    try:
        duration = float(duration_value)
    except (TypeError, ValueError) as error:
        raise ProcessingError("The input has no usable container duration.") from error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kuaishou_tianbaixinglun_") as temporary:
        commands = build_commands(
            str(ffmpeg), input_path, output_path, Path(temporary),
            geometry_frame, duration, 0,
        )
        for command in commands:
            run_command(command)
    return probe(ffprobe, output_path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce and structurally verify the captured "
            "kuaishou_tianbaixinglun FFmpeg pipeline."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument(
        "--geometry-frame",
        type=Path,
        default=CAPTURED_GEOMETRY_FRAME,
        help="Geometry PNG generated by the application (default: captured baseline artifact).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="JSON report path (default: OUTPUT.verification.json).",
    )
    args = parser.parse_args()
    report_path = args.report or args.output.with_suffix(args.output.suffix + ".verification.json")
    report: dict[str, Any] = {
        "mode": "kuaishou_tianbaixinglun",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input.resolve()),
        "reference": str(args.reference.resolve()),
        "output": str(args.output.resolve()),
        "geometry_frame": str(args.geometry_frame.resolve()),
        "status": "processing_error",
    }

    try:
        if not args.reference.is_file():
            raise ProcessingError(f"Reference file does not exist: {args.reference}")
        ffmpeg = resolve_tool("ffmpeg.exe")
        ffprobe = resolve_tool("ffprobe.exe")
        actual_probe = produce(
            ffmpeg,
            ffprobe,
            args.input.resolve(),
            args.output.resolve(),
            args.geometry_frame.resolve(),
        )
        expected_probe = probe(ffprobe, args.reference.resolve())
        expected_signature = signature(expected_probe)
        actual_signature = signature(actual_probe)
        differences = compare(expected_signature, actual_signature)
        report.update(
            {
                "ffmpeg": str(ffmpeg),
                "ffprobe": str(ffprobe),
                "expected_signature": expected_signature,
                "actual_signature": actual_signature,
                "differences": differences,
                "comparison_policy": {
                    "ignored": [
                        "file size",
                        "bitrate",
                        "whole-file hash",
                        "encoded packet bytes",
                        "creation timestamps",
                        "pixel hashes and visual similarity metrics",
                    ],
                    "format_duration_tolerance_seconds": 0.001,
                    "format_duration_tolerance_requires_exact_stream_durations_and_frame_counts": True,
                },
                "capture_evidence": {
                    "active_baseline": str(CAPTURE_RUN),
                    "geometry_frame": str(CAPTURED_GEOMETRY_FRAME),
                    "filter_script": "engine.native_core.tianbaixinglun_pipeline_plan",
                    "response_files": "No :ffarg response-file paths were observed.",
                    "unknown_transformations": [
                        "The application-internal algorithm that creates geometry_frame.png "
                        "was not exposed as a child process. The worker defaults to the exact "
                        "captured PNG and accepts --geometry-frame for other samples."
                    ],
                },
                "status": "passed" if not differences else "feature_mismatch",
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        write_json(report_path, report)
        print(f"Verification report: {report_path}")
        if differences:
            print(f"Feature mismatch: {len(differences)} structural difference(s).")
            return 2
        print("Structural verification passed.")
        return 0
    except (ProcessingError, OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        report["error"] = str(error)
        report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(report_path, report)
        print(f"Processing failed: {error}", file=sys.stderr)
        print(f"Verification report: {report_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
