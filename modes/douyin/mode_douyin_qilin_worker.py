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
from modes.douyin.qilin_sps_compat import apply_qilin_sps_compatibility


SCRIPT_DIR = Path(__file__).resolve().parent
CAPTURE_RUN = "run_20261004_203528_revalidation"
ARTIFACTS_DIR = SCRIPT_DIR / "qilin_artifacts"
X265_PARAMS = (
    "bframes=4:no-scenecut=1:keyint=16100:min-keyint=161:no-info=1:no-hrd=1:"
    "vui-timing-info=0:vui-hrd-info=0:repeat-headers=0:no-open-gop=1"
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
FORMAT_TAGS = (
    "major_brand",
    "minor_version",
    "compatible_brands",
    "title",
    "artist",
    "album",
    "comment",
    "location",
    "location-eng",
)


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
        arguments, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False
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
            changes.extend(
                _differences(left, right, f"{path}[{index}]", skip_format_duration)
            )
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
    if expected_duration is not None or actual_duration is not None:
        try:
            delta = abs(float(expected_duration) - float(actual_duration))
        except (TypeError, ValueError):
            delta = float("inf")
        if delta > 0.001 or not stream_timing_matches:
            changes.append(
                {
                    "path": "$.format.duration",
                    "expected": expected_duration,
                    "actual": actual_duration,
                    "tolerance_seconds": 0.001 if stream_timing_matches else 0,
                }
            )
    return changes


def build_commands(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    work: Path,
    width: int,
    height: int,
    threads: int,
    video_encoder: str,
    encoder_options: tuple[str, ...] = (),
    seed: int | None = None,
) -> list[list[str]]:
    plan = _native_core.qilin_pipeline_plan(width, height, seed)
    work.mkdir(parents=True, exist_ok=True)
    frame = work / "frame.jpg"
    geo = work / "geo.png"
    rotation = work / "rot.png"
    grid_graph_file = work / "grid_filter.txt"
    blend_graph_file = work / "blend_filter.txt"
    grid = work / "grid.mkv"
    blend = work / "blend.mkv"
    grid_graph_file.write_text(plan["grid_graph"], encoding="utf-8")
    blend_graph_file.write_text(plan["blend_graph"], encoding="utf-8")

    commands = [
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", plan["frame_seek"],
            "-i", str(input_path), "-frames:v", "1", "-q:v", "2", str(frame),
        ],
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", plan["geo_source"],
            "-frames:v", "1", str(geo),
        ],
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", plan["rotation_source"],
            "-frames:v", "1", str(rotation),
        ],
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
            "-threads", str(threads), "-loop", "1", "-i", str(frame),
            "-loop", "1", "-i", str(geo), "-loop", "1", "-i", str(rotation),
            "-/filter_complex", str(grid_graph_file), "-map", "[grid]",
            "-t", "10.0", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "16", "-pix_fmt", "yuv420p", "-r", "30",
            "-fps_mode", "cfr", "-an", "-f", "matroska", str(grid),
        ],
    ]
    blend_command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-threads", str(threads), "-i", str(input_path), "-stream_loop", "-1",
        "-i", str(grid), "-/filter_complex", str(blend_graph_file),
        "-map", "[vout]", "-map", "[aout]", "-shortest", "-c:v", video_encoder,
    ]
    if video_encoder == "libx265":
        blend_command.extend([
            "-preset", "fast", "-crf", "24", "-x265-params", X265_PARAMS,
        ])
    else:
        blend_command.extend(encoder_options)
    blend_command.extend([
        "-tag:v", "hvc1", "-force_key_frames", plan["keyframes"],
        "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
        "-color_trc", "bt709", "-color_primaries", "bt709", "-color_range", "tv",
        "-r", "30", "-fps_mode", "cfr", "-field_order", "tb",
    ])
    if video_encoder == "libx265":
        blend_command.extend(["-flags:v", "+ilme+ildct"])
    blend_command.extend([
        "-video_track_timescale", "15360", "-c:a", "aac", "-b:a", "72k",
        "-ac", "2", "-ar", "44100", "-metadata",
        f"creation_time={plan['creation_time']}", "-metadata", "encoder=vcodec2",
        "-f", "matroska", str(blend),
    ])
    commands.extend([
        blend_command,
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
            "-threads", str(threads), "-i", str(blend), "-c", "copy",
            "-movflags", "+faststart", str(output_path),
        ],
    ])
    return commands


def produce(
    ffmpeg: Path, ffprobe: Path, input_path: Path, output_path: Path
) -> dict[str, Any]:
    if not input_path.is_file():
        raise ProcessingError(f"Input file does not exist: {input_path}")
    source_probe = probe(ffprobe, input_path)
    video_stream = next(
        (stream for stream in source_probe.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ProcessingError("The input has no video stream.")
    width = int(video_stream["width"])
    height = int(video_stream["height"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise ProcessingError(f"Refusing to overwrite existing output: {output_path}")
    output_path_resolved = output_path.resolve()
    if output_path_resolved == input_path.resolve():
        raise ProcessingError("Input and output paths must be different.")

    with tempfile.TemporaryDirectory(prefix="douyin_qilin_") as temporary:
        work = Path(temporary)
        commands = build_commands(
            str(ffmpeg),
            input_path,
            output_path,
            work,
            width,
            height,
            12,
            "libx265",
        )
        for command in commands:
            run_command(command)

    compatibility = apply_qilin_sps_compatibility(output_path)
    print(
        "Qilin platform compatibility (nonstandard SPS): "
        f"offset={compatibility.offset}, {compatibility.before:#04x} -> {compatibility.after:#04x}",
        file=sys.stderr,
    )
    return probe(ffprobe, output_path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce and structurally verify the captured douyin_qilin FFmpeg pipeline."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument(
        "--report",
        type=Path,
        help="JSON report path (default: OUTPUT.verification.json).",
    )
    args = parser.parse_args()
    report_path = args.report or args.output.with_suffix(args.output.suffix + ".verification.json")
    started = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "mode": "douyin_qilin",
        "started_at_utc": started,
        "input": str(args.input.resolve()),
        "reference": str(args.reference.resolve()),
        "output": str(args.output.resolve()),
        "status": "processing_error",
    }

    try:
        if not args.reference.is_file():
            raise ProcessingError(f"Reference file does not exist: {args.reference}")
        ffmpeg = resolve_tool("ffmpeg.exe")
        ffprobe = resolve_tool("ffprobe.exe")
        actual_probe = produce(ffmpeg, ffprobe, args.input.resolve(), args.output.resolve())
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
                "platform_compatibility": {
                    "enabled": True,
                    "scope": "Qilin outputs only",
                    "nonstandard_sps": True,
                    "validation": "User-validated upload controls on 2026-10-05; local playback may flicker.",
                },
                "capture_evidence": {
                    "source_run": CAPTURE_RUN,
                    "filter_graphs": [
                        str(ARTIFACTS_DIR / "grid_filter.txt"),
                        str(ARTIFACTS_DIR / "blend_filter.txt"),
                    ],
                    "response_files": "No :ffarg response-file paths were observed.",
                    "visual_limitations": [
                        "A revalidation capture preserved the original 198x188 geo.png and rot.png mosaics.",
                        "This worker procedurally generates the same 6x6 and 4x6 randomized mosaic classes; exact random values are intentionally different per run.",
                        "Frame extraction time, grid filters, audio perturbations, keyframes, and creation metadata are randomized within observed capture ranges.",
                        "The captured anoisesrc produces nondeterministic audio noise; pixel and audio-sample equality are not asserted.",
                        "The pass covers the stable ffprobe structure only and does not establish visual or perceptual equality.",
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
