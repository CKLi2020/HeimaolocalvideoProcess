#!/usr/bin/env python3
"""Reproduce captured shipin_tianjia encoding and verify stable media features."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


X264_PARAMS = "aq-mode=2:aq-strength=1.00"
UNKNOWN_TRANSFORMATION = (
    "The tool used a second, infinitely looped video in a transient filter_complex. "
    "That response stream was deleted before capture, so this worker reproduces the "
    "demonstrated media structure but does not claim pixel-equivalent visual compositing."
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
    return json.loads(
        run_capture(
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
    )


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
    effect_input: Path,
    output_path: Path,
    reference: dict[str, Any],
    threads: int,
    video_encoder: str = "libx264",
    encoder_options: Sequence[str] = (),
    pixel_format: str | None = None,
) -> list[str]:
    return build_command_with_encoder(
        ffmpeg, input_path, effect_input, output_path, reference, threads,
        video_encoder, encoder_options, pixel_format,
    )


def build_command_with_encoder(
    ffmpeg: str,
    input_path: Path,
    effect_input: Path,
    output_path: Path,
    reference: dict[str, Any],
    threads: int,
    video_encoder: str,
    encoder_options: Sequence[str],
    pixel_format: str | None,
) -> list[str]:
    video = first_stream(reference, "video")
    audio = first_stream(reference, "audio")
    width = int(video["width"])
    height = int(video["height"])
    frame_rate = video["r_frame_rate"].split("/")[0]
    frame_count = int(video["nb_read_frames"])
    audio_duration = audio["duration"]
    filter_complex = (
        f"[0:v:0]scale={width}:{height}:flags=lanczos,setsar=1,fps={frame_rate},"
        f"trim=end_frame={frame_count},setpts=PTS-STARTPTS[v];"
        f"[0:a:0]aresample={audio['sample_rate']},"
        f"aformat=channel_layouts={audio['channel_layout']},apad,"
        f"atrim=duration={audio_duration},asetpts=PTS-STARTPTS[a]"
    )
    pixel_format = pixel_format or video.get("pix_fmt") or "yuv420p"
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
        "-stream_loop", "-1",
        "-i", str(effect_input),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-r", frame_rate,
        "-fps_mode", "cfr",
        "-c:v", video_encoder,
    ]
    if video_encoder == "libx264":
        command.extend([
            "-preset", "medium",
            "-tune", "film",
            "-crf", "17",
            "-profile:v", "high",
            "-level:v", "4.2",
            "-bf", "0",
            "-refs", "3",
            "-g", "120",
            "-keyint_min", "120",
            "-sc_threshold", "0",
            "-force_key_frames", "expr:gte(t,n_forced*1)",
            "-x264-params", X264_PARAMS,
        ])
    else:
        command.extend(encoder_options)
    command.extend([
        "-pix_fmt", pixel_format,
        "-colorspace", video.get("color_space", "bt709"),
        "-color_trc", "bt709",
        "-color_primaries", "bt709",
        "-color_range", video.get("color_range", "tv"),
        "-video_track_timescale", "15360",
        "-threads", str(threads),
        "-c:a", "aac",
        "-b:a", "72k",
        "-ac", str(audio["channels"]),
        "-ar", audio["sample_rate"],
        "-tag:v", "avc1",
        "-movflags", "+faststart",
        str(output_path),
    ])
    return command


def process(
    ffmpeg: str,
    input_path: Path,
    effect_input: Path,
    output_path: Path,
    reference: dict[str, Any],
    threads: int,
) -> None:
    command = build_command(ffmpeg, input_path, effect_input, output_path, reference, threads)
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise ProcessingError(f"ffmpeg failed with exit code {completed.returncode}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Reproduce captured shipin_tianjia stable features.")
    result.add_argument("input_path", type=Path)
    result.add_argument("output_path", type=Path)
    result.add_argument("--effect-input", required=True, type=Path, help="Second video selected by the mode")
    result.add_argument("--reference", required=True, type=Path, help="shipin_tianjia output made by the tool")
    result.add_argument("--threads", type=int, default=6)
    result.add_argument("--report", type=Path)
    return result


def main() -> int:
    arguments = parser().parse_args()
    root = Path(__file__).resolve().parent
    input_path = arguments.input_path.expanduser().resolve()
    effect_input = arguments.effect_input.expanduser().resolve()
    output_path = arguments.output_path.expanduser().resolve()
    reference_path = arguments.reference.expanduser().resolve()
    try:
        if not input_path.is_file() or not effect_input.is_file() or not reference_path.is_file():
            raise ProcessingError("Input, effect input, or reference file does not exist.")
        if arguments.threads < 1:
            raise ProcessingError("--threads must be at least 1.")
        ffmpeg = resolve_tool(root, "ffmpeg.exe")
        ffprobe = resolve_tool(root, "ffprobe.exe")
        reference_report = probe(ffprobe, reference_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        process(ffmpeg, input_path, effect_input, output_path, reference_report, arguments.threads)
        output_report = probe(ffprobe, output_path)
        expected = stable_features(reference_report)
        actual = stable_features(output_report)
        errors = differences(expected, actual)
        report = {
            "passed": not errors,
            "mode": "shipin_tianjia",
            "reference": str(reference_path),
            "output": str(output_path),
            "effect_input": str(effect_input),
            "comparison_policy": (
                "Stable ffprobe structure, frame and packet counts; format duration allows "
                "1 ms muxer rounding. Bitrate, size, hashes and pixels are excluded."
            ),
            "unknown_transformation": UNKNOWN_TRANSFORMATION,
            "errors": errors,
            "expected": expected,
            "actual": actual,
        }
        report_path = arguments.report or output_path.with_suffix(".shipin_tianjia-report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        print(f"shipin_tianjia stable features match. Report: {report_path}", file=sys.stderr)
        return 0
    except (OSError, ValueError, KeyError, ProcessingError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())