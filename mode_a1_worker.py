#!/usr/bin/env python3
"""Reproduce captured mode A1 encoding and verify stable media features."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence


X265_PARAMS = (
    "bframes=4:no-scenecut=1:keyint=27000:min-keyint=270:no-info=1:"
    "no-hrd=1:vui-timing-info=0:vui-hrd-info=0:repeat-headers=0:no-open-gop=1"
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
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    )
    return json.loads(output)


def first_stream(report: dict[str, Any], codec_type: str) -> dict[str, Any]:
    for stream in report.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    raise ProcessingError(f"Reference has no {codec_type} stream.")


def decimal_rate(rate: str) -> str:
    value = Fraction(rate)
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.8f}".rstrip("0").rstrip(".")


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
            "disposition": stream.get("disposition"),
            "tags": stream.get("tags"),
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
                    "field_order": stream.get("field_order"),
                    "r_frame_rate": stream.get("r_frame_rate"),
                    "avg_frame_rate": stream.get("avg_frame_rate"),
                    "duration": stream.get("duration"),
                    "nb_frames": stream.get("nb_frames"),
                }
            )
        elif stream.get("codec_type") == "audio":
            common.update(
                {
                    "sample_fmt": stream.get("sample_fmt"),
                    "sample_rate": stream.get("sample_rate"),
                    "channels": stream.get("channels"),
                    "channel_layout": stream.get("channel_layout"),
                    "duration": stream.get("duration"),
                    "nb_frames": stream.get("nb_frames"),
                }
            )
        streams.append(common)
    return {
        "format": {
            "format_name": format_info.get("format_name"),
            "start_time": format_info.get("start_time"),
            "duration": format_info.get("duration"),
            "tags": format_info.get("tags"),
        },
        "streams": streams,
    }


def differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    if path == "format.duration":
        try:
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
    reference: dict[str, Any],
    threads: int,
    video_encoder: str = "libx265",
    encoder_options: Sequence[str] = (),
) -> list[str]:
    video = first_stream(reference, "video")
    audio = first_stream(reference, "audio")
    width = int(video["width"])
    height = int(video["height"])
    frame_rate = decimal_rate(video["r_frame_rate"])
    video_duration = video["duration"]
    audio_duration = audio["duration"]

    field_filter = ",setfield=tff" if video_encoder == "libx265" else ""
    filter_complex = (
        f"[0:v:0]scale={width}:{height}:flags=lanczos,setsar=1{field_filter},"
        f"trim=duration={video_duration},setpts=PTS-STARTPTS[v];"
        f"[0:a:0]aresample={audio['sample_rate']},aformat=channel_layouts={audio['channel_layout']},apad,"
        f"atrim=duration={audio_duration},asetpts=PTS-STARTPTS[a]"
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
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", video_encoder,
    ]
    if video_encoder == "libx265":
        command.extend([
            "-preset", "fast",
            "-crf", "16",
            "-x265-params", X265_PARAMS,
        ])
    else:
        command.extend(encoder_options)
    command.extend([
        "-tag:v", "hvc1",
        "-force_key_frames", "0,9.000,10.000,11.000",
        "-sc_threshold", "0",
        "-pix_fmt", video["pix_fmt"],
        "-colorspace", video.get("color_space", "bt709"),
        "-color_trc", "bt709",
        "-color_primaries", "bt709",
        "-color_range", video.get("color_range", "tv"),
        "-r", frame_rate,
        "-fps_mode", "cfr",
        "-video_track_timescale", str(Fraction(video["time_base"]).denominator),
        "-threads", str(threads),
        "-c:a", "aac",
        "-b:a", "72k",
        "-ac", str(audio["channels"]),
        "-ar", audio["sample_rate"],
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output_path),
    ])
    if video_encoder == "libx265":
        field_index = command.index("-video_track_timescale")
        command[field_index:field_index] = [
            "-field_order", video.get("field_order", "tb"),
            "-flags:v", "+ilme+ildct",
        ]
    return command


def process(ffmpeg: str, input_path: Path, output_path: Path, reference: dict[str, Any], threads: int) -> None:
    command = build_command(ffmpeg, input_path, output_path, reference, threads)
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise ProcessingError(f"ffmpeg failed with exit code {completed.returncode}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Reproduce captured mode A1 and compare features.")
    result.add_argument("input_path", type=Path)
    result.add_argument("output_path", type=Path)
    result.add_argument("--reference", required=True, type=Path, help="Mode A1 output made by the tool")
    result.add_argument("--threads", type=int, default=6)
    result.add_argument("--report", type=Path)
    return result


def main() -> int:
    arguments = parser().parse_args()
    root = Path(__file__).resolve().parent
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
        reference_report = probe(ffprobe, reference_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        process(ffmpeg, input_path, output_path, reference_report, arguments.threads)
        output_report = probe(ffprobe, output_path)
        expected = stable_features(reference_report)
        actual = stable_features(output_report)
        errors = differences(expected, actual)
        report = {
            "passed": not errors,
            "reference": str(reference_path),
            "output": str(output_path),
            "comparison_policy": (
                "Stable ffprobe features; format duration allows 1 ms muxer rounding. "
                "Bitrate, size, hashes and pixels are excluded."
            ),
            "errors": errors,
            "expected": expected,
            "actual": actual,
        }
        report_path = arguments.report or output_path.with_suffix(".a1-report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        print(f"A1 stable features match. Report: {report_path}", file=sys.stderr)
        return 0
    except (OSError, ValueError, KeyError, ProcessingError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())