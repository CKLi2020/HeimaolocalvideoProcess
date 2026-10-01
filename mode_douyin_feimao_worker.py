from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = SCRIPT_DIR / "capture_douyin_feimao"
ACTIVE_RUN = CAPTURE_DIR / "run_20260928_202138"
RESPONSE_DIR = ACTIVE_RUN / "ffargs" / "active"
DEFAULT_METADATA_URL = "http://xhm.zjwhcmxy.com/modes/xiaohongshu/xhs4.json.php?meta=1"
STREAM_FIELDS = (
    "index",
    "codec_type",
    "codec_name",
    "profile",
    "level",
    "codec_tag_string",
    "width",
    "height",
    "coded_width",
    "coded_height",
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
    "duration",
    "nb_frames",
    "sample_fmt",
    "sample_rate",
    "channels",
    "channel_layout",
)
STREAM_TAGS = ("language", "handler_name", "vendor_id", "encoder")
FORMAT_TAGS = ("major_brand", "minor_version", "compatible_brands", "encoder")


class WorkerError(Exception):
    pass


def find_tool(name: str) -> str:
    candidates = (SCRIPT_DIR / "bin" / name, SCRIPT_DIR / name)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise WorkerError(f"Unable to find {name} in bin/, the script directory, or PATH")


def read_response(name: str) -> str:
    path = RESPONSE_DIR / name
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except OSError as error:
        raise WorkerError(f"Unable to read captured response file {path}: {error}") from error


def probe(ffprobe: str, media_path: Path) -> dict:
    command = [
        ffprobe,
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
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise WorkerError(f"ffprobe failed for {media_path}: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise WorkerError(f"ffprobe returned invalid JSON for {media_path}: {error}") from error


def select_tags(tags: dict | None, allowed: tuple[str, ...]) -> dict:
    tags = tags or {}
    return {key: tags[key] for key in allowed if key in tags}


def signature(data: dict) -> dict:
    streams = []
    for stream in data.get("streams", []):
        item = {key: stream.get(key) for key in STREAM_FIELDS}
        item["disposition"] = stream.get("disposition", {})
        item["tags"] = select_tags(stream.get("tags"), STREAM_TAGS)
        streams.append(item)

    media_format = data.get("format", {})
    return {
        "streams": streams,
        "format": {
            "format_name": media_format.get("format_name"),
            "start_time": media_format.get("start_time"),
            "duration": media_format.get("duration"),
            "nb_streams": media_format.get("nb_streams"),
            "tags": select_tags(media_format.get("tags"), FORMAT_TAGS),
        },
        "program_count": len(data.get("programs", [])),
        "chapter_count": len(data.get("chapters", [])),
    }


def compare_signatures(expected: dict, actual: dict) -> list[dict]:
    differences = []
    streams_match_duration_and_count = len(expected.get("streams", [])) == len(actual.get("streams", [])) and all(
        expected_stream.get("duration") == actual_stream.get("duration")
        and expected_stream.get("nb_frames") == actual_stream.get("nb_frames")
        for expected_stream, actual_stream in zip(expected.get("streams", []), actual.get("streams", []))
    )

    def compare(path: str, expected_value, actual_value):
        if isinstance(expected_value, dict) and isinstance(actual_value, dict):
            for key in sorted(set(expected_value) | set(actual_value)):
                if key not in expected_value or key not in actual_value:
                    differences.append({"field": f"{path}.{key}", "expected": expected_value.get(key), "actual": actual_value.get(key)})
                else:
                    compare(f"{path}.{key}", expected_value[key], actual_value[key])
            return
        if isinstance(expected_value, list) and isinstance(actual_value, list):
            if len(expected_value) != len(actual_value):
                differences.append({"field": f"{path}.length", "expected": len(expected_value), "actual": len(actual_value)})
                return
            for index, (expected_item, actual_item) in enumerate(zip(expected_value, actual_value)):
                compare(f"{path}[{index}]", expected_item, actual_item)
            return
        if path == "signature.format.duration" and streams_match_duration_and_count:
            try:
                if abs(float(expected_value) - float(actual_value)) <= 0.001:
                    return
            except (TypeError, ValueError):
                pass
        if expected_value != actual_value:
            differences.append({"field": path, "expected": expected_value, "actual": actual_value})

    compare("signature", expected, actual)
    return differences


def build_command(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    metadata_url: str,
    video_encoder: str = "libx265",
    encoder_options: tuple[str, ...] = (),
    threads: int = 6,
    video_tag: str | None = None,
) -> list[str]:
    filter_graph = (ACTIVE_RUN / "filter_complex.txt").read_text(encoding="utf-8-sig")
    if video_encoder != "libx265":
        # Hardware HEVC encoders reject interlaced-flagged frames.
        filter_graph = filter_graph.replace(",setfield=tff", "")
    command = [
        ffmpeg,
        "-progress",
        "pipe:2",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-stats",
        "-stats_period",
        "0.5",
        "-threads",
        str(threads),
        "-i",
        str(input_path),
        "-f",
        read_response("a001"),
        "-i",
        metadata_url,
        "-filter_complex",
        filter_graph,
        "-map",
        read_response("a003"),
        "-map",
        read_response("a004"),
        "-map_metadata",
        "1",
        "-shortest",
        "-c:v",
        video_encoder,
    ]
    if video_encoder == "libx265":
        command.extend([
            "-preset",
            "fast",
            "-crf",
            "16",
            "-x265-params",
            "bframes=4:no-scenecut=1:keyint=27000:min-keyint=270:no-info=1:no-hrd=1:vui-timing-info=0:vui-hrd-info=0:repeat-headers=0:no-open-gop=1",
        ])
        command.extend(encoder_options)
        command.extend(["-field_order", "tb", "-flags:v", "+ilme+ildct"])
    else:
        command.extend(encoder_options)
    command.extend([
        "-tag:v",
        video_tag or read_response("a006"),
        "-force_key_frames",
        "0,9.000,10.000,11.000",
        "-pix_fmt",
        read_response("a007"),
        "-colorspace",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_range",
        "tv",
        "-r",
        read_response("a008"),
        "-fps_mode",
        "cfr",
        "-video_track_timescale",
        "16000",
        "-threads",
        str(threads),
        "-c:a",
        read_response("a009"),
        "-b:a",
        read_response("a010"),
        "-ac",
        read_response("a011"),
        "-ar",
        read_response("a012"),
        "-movflags",
        "+faststart",
        "-f",
        read_response("a013"),
        str(output_path),
    ])
    return command


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce and verify the captured douyin_feimao mode.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--metadata-url", default=DEFAULT_METADATA_URL)
    parser.add_argument("--report", type=Path, default=CAPTURE_DIR / "comparison.json")
    args = parser.parse_args()

    report = {
        "mode": "douyin_feimao",
        "input": str(args.input.resolve()),
        "reference": str(args.reference.resolve()),
        "output": str(args.output.resolve()),
        "metadata_url": args.metadata_url,
        "expected_signature": None,
        "actual_signature": None,
        "differences": [],
        "policy": {
            "compared": "ordered streams, codec/profile/tag, dimensions, pixel/color/field properties, rates, timestamps, durations, frame counts, audio layout, dispositions, stable stream/container tags, format and chapter structure",
            "excluded": ["file size", "bitrate", "format comment and other dynamic remote metadata", "creation time", "encoded bytes and whole-file equality", "pixel hashes and image-quality scores"],
            "tolerances": {"format.duration": "0.001 seconds only; stream durations and frame counts are still compared exactly"},
            "nondeterminism": ["the captured graph includes time-varying overlays and noise; encoded bytes and visual hashes are not equality criteria", "the metadata endpoint has returned varying device comments across repeated tool runs"],
            "unknown": ["the metadata endpoint response body is not snapshotted; only its URL and mapped output metadata are observed"],
        },
        "passed": False,
    }

    try:
        input_path = args.input.resolve(strict=True)
        reference_path = args.reference.resolve(strict=True)
        output_path = args.output.resolve()
        if input_path == reference_path or input_path == output_path or reference_path == output_path:
            raise WorkerError("Input, output, and reference paths must be distinct")
        ffmpeg = find_tool("ffmpeg.exe")
        ffprobe = find_tool("ffprobe.exe")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_command(ffmpeg, input_path, output_path, args.metadata_url)
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        report["ffmpeg_command"] = command
        report["ffmpeg_stderr"] = process.stderr[-12000:]
        if process.returncode != 0:
            report["processing_error"] = f"ffmpeg exited with code {process.returncode}"
            write_report(args.report, report)
            return 1

        expected_data = probe(ffprobe, reference_path)
        actual_data = probe(ffprobe, output_path)
        expected_signature = signature(expected_data)
        actual_signature = signature(actual_data)
        differences = compare_signatures(expected_signature, actual_signature)
        report["expected_signature"] = expected_signature
        report["actual_signature"] = actual_signature
        report["differences"] = differences
        report["passed"] = not differences
        report["result"] = "pass" if not differences else "feature_mismatch"
        write_report(args.report, report)
        return 0 if not differences else 2
    except (OSError, WorkerError, subprocess.SubprocessError) as error:
        report["processing_error"] = str(error)
        write_report(args.report, report)
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
