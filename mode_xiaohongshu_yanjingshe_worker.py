import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = SCRIPT_DIR / "capture_xiaohongshu_yanjingshe"
DEFAULT_METADATA_URL = "http://xhm.zjwhcmxy.com/modes/xiaohongshu/xhs4.json.php?meta=1"
FILTER_GRAPH = (
    "[0:v]fps=30,scale=w='if(gte(iw\\,ih)\\,1024\\,576)':"
    "h='if(gte(iw\\,ih)\\,576\\,1024)':flags=lanczos,setsar=1,"
    "format=yuv420p,setpts=PTS*0.995322[vout];"
    "anoisesrc=color=pink:amplitude=0.000568:sample_rate=44100,"
    "aformat=channel_layouts=stereo[bg_noise];"
    "[0:a]aresample=44100,aformat=channel_layouts=stereo,atempo=1.0047,"
    "vibrato=f=0.266:d=0.034,volume=1.051[a_mod];"
    "[a_mod][bg_noise]amix=inputs=2:duration=first,"
    "aformat=channel_layouts=stereo,alimiter=limit=0.944,"
    "asetpts=PTS-STARTPTS[aout]"
)
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
    "duration_ts",
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
    for candidate in (SCRIPT_DIR / "bin" / name, SCRIPT_DIR / name):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise WorkerError(f"Unable to find {name} in bin/, the script directory, or PATH")


def run_probe(ffprobe: str, media_path: Path) -> dict:
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
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if process.returncode:
        raise WorkerError(f"ffprobe failed for {media_path}: {process.stderr.strip()}")
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise WorkerError(f"ffprobe returned invalid JSON for {media_path}: {error}") from error


def stable_tags(tags: dict | None, keys: tuple[str, ...]) -> dict:
    tags = tags or {}
    return {key: tags[key] for key in keys if key in tags}


def signature(data: dict) -> dict:
    streams = []
    for stream in data.get("streams", []):
        item = {key: stream.get(key) for key in STREAM_FIELDS}
        item["disposition"] = stream.get("disposition", {})
        item["tags"] = stable_tags(stream.get("tags"), STREAM_TAGS)
        streams.append(item)

    chapters = []
    for chapter in data.get("chapters", []):
        chapters.append(
            {
                key: chapter.get(key)
                for key in ("id", "time_base", "start", "end", "start_time", "end_time")
            }
            | {"tags": chapter.get("tags", {})}
        )

    programs = []
    for program in data.get("programs", []):
        programs.append(
            {
                "program_id": program.get("program_id"),
                "program_num": program.get("program_num"),
                "stream_indexes": [stream.get("index") for stream in program.get("streams", [])],
                "tags": program.get("tags", {}),
            }
        )

    media_format = data.get("format", {})
    return {
        "streams": streams,
        "format": {
            "format_name": media_format.get("format_name"),
            "start_time": media_format.get("start_time"),
            "duration": media_format.get("duration"),
            "nb_streams": media_format.get("nb_streams"),
            "tags": stable_tags(media_format.get("tags"), FORMAT_TAGS),
        },
        "programs": programs,
        "chapters": chapters,
    }


def compare_signatures(expected: dict, actual: dict) -> list[dict]:
    differences = []
    streams_match_duration_and_count = len(expected["streams"]) == len(actual["streams"]) and all(
        expected_stream.get("duration") == actual_stream.get("duration")
        and expected_stream.get("nb_frames") == actual_stream.get("nb_frames")
        for expected_stream, actual_stream in zip(expected["streams"], actual["streams"])
    )

    def compare(path: str, expected_value, actual_value) -> None:
        if isinstance(expected_value, dict) and isinstance(actual_value, dict):
            for key in sorted(set(expected_value) | set(actual_value)):
                if key not in expected_value or key not in actual_value:
                    differences.append(
                        {"field": f"{path}.{key}", "expected": expected_value.get(key), "actual": actual_value.get(key)}
                    )
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
    video_encoder: str = "libx264",
    encoder_options: tuple[str, ...] = (),
    threads: int = 6,
) -> list[str]:
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
        "ffmetadata",
        "-i",
        metadata_url,
        "-filter_complex",
        FILTER_GRAPH,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-map_metadata",
        "1",
        "-shortest",
        "-r",
        "120",
        "-fps_mode",
        "cfr",
        "-c:v",
        video_encoder,
    ]
    if video_encoder == "libx264":
        command.extend([
            "-b:v",
            "12000k",
            "-maxrate",
            "18000k",
            "-bufsize",
            "24000k",
            "-bf",
            "0",
            "-refs",
            "3",
            "-keyint_min",
            "120",
            "-sc_threshold",
            "0",
        ])
    else:
        command.extend(["-b:v", "12000k"])
        command.extend(encoder_options)
    command.extend([
        "-profile:v",
        "high",
        "-level:v",
        "4.2",
        "-g",
        "120",
        "-force_key_frames",
        "expr:gte(t,n_forced*1)",
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_range",
        "tv",
        "-video_track_timescale",
        "15360",
        "-threads",
        str(threads),
        "-c:a",
        "aac",
        "-b:a",
        "72k",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-tag:v",
        "avc1",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    return command


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce and verify xiaohongshu_yanjingshe mode.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--metadata-url", default=DEFAULT_METADATA_URL)
    parser.add_argument("--report", type=Path, default=CAPTURE_DIR / "comparison.json")
    args = parser.parse_args()

    report = {
        "mode": "xiaohongshu_yanjingshe",
        "input": str(args.input.resolve()),
        "reference": str(args.reference.resolve()),
        "output": str(args.output.resolve()),
        "metadata_url": args.metadata_url,
        "expected_signature": None,
        "actual_signature": None,
        "differences": [],
        "policy": {
            "compared": "ordered streams, types, codecs/profiles/tags, dimensions, pixel/color/field properties, rates, timestamps, durations, frame counts, audio layout, dispositions, stable container tags, programs, and chapters",
            "excluded": ["file size", "bitrate", "remote comment and other volatile metadata", "creation time", "encoded bytes and whole-file equality", "pixel hashes and image-quality scores"],
            "tolerances": {"format.duration": "0.001 seconds only when every stream duration and frame count matches exactly"},
            "nondeterminism": ["anoisesrc generates pink noise; encoded audio samples and whole-file bytes are not equality criteria"],
            "unknown": ["the remote ffmetadata response body was not captured; its mapped comment may change between runs"],
        },
        "passed": False,
    }

    try:
        input_path = args.input.resolve(strict=True)
        reference_path = args.reference.resolve(strict=True)
        output_path = args.output.resolve()
        if len({input_path, reference_path, output_path}) != 3:
            raise WorkerError("Input, output, and reference paths must be distinct")

        ffmpeg = find_tool("ffmpeg.exe")
        ffprobe = find_tool("ffprobe.exe")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_command(ffmpeg, input_path, output_path, args.metadata_url)
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        report["ffmpeg_command"] = command
        report["ffmpeg_stderr"] = process.stderr[-12000:]
        if process.returncode:
            report["processing_error"] = f"ffmpeg exited with code {process.returncode}"
            write_report(args.report, report)
            return 1

        expected = signature(run_probe(ffprobe, reference_path))
        actual = signature(run_probe(ffprobe, output_path))
        differences = compare_signatures(expected, actual)
        report["input_sha256"] = sha256(input_path)
        report["reference_sha256"] = sha256(reference_path)
        report["expected_signature"] = expected
        report["actual_signature"] = actual
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