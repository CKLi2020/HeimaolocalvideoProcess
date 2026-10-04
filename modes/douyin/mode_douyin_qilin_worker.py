from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


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


def _partition(total: int, count: int, rng: random.Random) -> list[tuple[int, int]]:
    minimum = 8
    while True:
        cuts = sorted(rng.sample(range(minimum, total - minimum), count - 1))
        points = [0, *cuts, total]
        if all(right - left >= minimum for left, right in zip(points, points[1:])):
            return list(zip(points, points[1:]))


def _random_color(rng: random.Random) -> str:
    return "0x%02x%02x%02x" % tuple(rng.randint(30, 250) for _ in range(3))


def _mosaic_source(columns: int, rows: int, rng: random.Random) -> str:
    width, height = 198, 188
    filters = [f"color=c=black:s={width}x{height}:r=1", "format=rgb24"]
    vertical_cells = _partition(height, rows, rng)
    for left, right in _partition(width, columns, rng):
        for top, bottom in vertical_cells:
            filters.append(
                "drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=fill"
                % (left, top, right - left, bottom - top, _random_color(rng))
            )
    return ",".join(filters)


def _build_grid_graph(rng: random.Random) -> str:
    lines = [
        "[0:v]split=9[a_0][a_1][a_2][a_3][a_4][a_5][a_6][a_7][a_8];",
        "[1:v]split=8[g_0][g_1][g_2][g_3][g_4][g_5][g_6][g_7];",
        (
            "[2:v]fps=30,scale=198:188:flags=lanczos,setsar=1,format=yuv420p,"
            "rotate='%.3f*t':ow=198:oh=188:c=black,crop=190:180:4:4,"
            "setsar=1,format=yuv420p,split=3[r0][r1][r2];"
        )
        % rng.uniform(0.2, 0.3),
    ]
    for index in range(17):
        source = "a" if index < 9 else "g"
        source_index = index if index < 9 else index - 9
        saturation = rng.uniform(0.9, 1.15)
        lines.append(
            (
                "[%s_%d]fps=30,scale=198:188:flags=lanczos,setsar=1,format=yuv420p,"
                "hue=h='%.6f*t+%.3f':s=%.3f,"
                "eq=brightness=%.3f:contrast=%.3f:saturation=%.3f,"
                "rotate='%.3f*sin(2*PI*%.3f*t)':ow=198:oh=188:c=black,"
                "crop=190:180:4:4,setsar=1,format=yuv420p[c%d];"
            )
            % (
                source,
                source_index,
                rng.uniform(25, 55),
                rng.uniform(0, 360),
                saturation,
                rng.uniform(-0.01, 0.04),
                rng.uniform(0.95, 1.06),
                saturation,
                rng.uniform(0.03, 0.06),
                rng.uniform(0.3, 1.0),
                index,
            )
        )
    inputs = "".join(f"[c{index}]" for index in range(17)) + "[r0][r1][r2]"
    layout = "|".join(f"{column * 190}_{row * 180}" for row in range(4) for column in range(5))
    lines.append(
        f"{inputs}xstack=inputs=20:layout={layout},"
        f"gblur=sigma={rng.uniform(0.8, 1.0):.3f},setsar=1,format=yuv420p[grid]"
    )
    return "\n".join(lines)


def _build_blend_graph(width: int, height: int, rng: random.Random) -> str:
    tempo = rng.uniform(1.004, 1.006)
    return (
        f"[0:v]fps=30,scale={width}:{height}:flags=lanczos,setsar=1,"
        f"format=yuv420p,setpts=PTS/{tempo:.4f}[main];"
        f"[1:v]fps=30,scale={width}:{height}:flags=lanczos,setsar=1,"
        "format=yuv420p[grid];"
        "[main][grid]blend=all_expr='if(lt(N\\,3)\\,A\\,"
        "if(eq(mod(Y\\,2)\\,0)\\,A\\,B))':shortest=1,"
        "setfield=tff,format=yuv420p[vout];"
        f"anoisesrc=color=pink:amplitude={rng.uniform(0.0008, 0.001):.6f}:"
        "sample_rate=44100,aformat=channel_layouts=stereo[bg_noise];"
        "[0:a]aresample=44100,aformat=channel_layouts=stereo,"
        f"atempo={tempo:.4f},vibrato=f={rng.uniform(0.3, 0.4):.3f}:"
        f"d={rng.uniform(0.04, 0.05):.3f},volume={rng.uniform(1.05, 1.1):.3f}[a_mod];"
        "[a_mod][bg_noise]amix=inputs=2:duration=first,"
        "aformat=channel_layouts=stereo,alimiter=limit=-0.5dB,"
        "asetpts=PTS-STARTPTS[aout]"
    )


def _creation_time(rng: random.Random) -> str:
    value = datetime.now(timezone.utc) - timedelta(
        days=rng.randint(7, 24), seconds=rng.randint(0, 86399)
    )
    return value.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


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
    rng = random.Random(seed) if seed is not None else random.Random(
        random.SystemRandom().getrandbits(64)
    )
    work.mkdir(parents=True, exist_ok=True)
    frame = work / "frame.jpg"
    geo = work / "geo.png"
    rotation = work / "rot.png"
    grid_graph_file = work / "grid_filter.txt"
    blend_graph_file = work / "blend_filter.txt"
    grid = work / "grid.mkv"
    blend = work / "blend.mkv"
    grid_graph_file.write_text(_build_grid_graph(rng), encoding="utf-8")
    blend_graph_file.write_text(_build_blend_graph(width, height, rng), encoding="utf-8")
    frame_seek = rng.uniform(0.5, 2.0)
    keyframes = "0,%.3f,%.3f" % (rng.uniform(5.5, 6.0), rng.uniform(6.6, 7.0))
    creation_time = _creation_time(rng)

    commands = [
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{frame_seek:.2f}",
            "-i", str(input_path), "-frames:v", "1", "-q:v", "2", str(frame),
        ],
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", _mosaic_source(6, 6, rng),
            "-frames:v", "1", str(geo),
        ],
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", _mosaic_source(4, 6, rng),
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
        "-tag:v", "hvc1", "-force_key_frames", keyframes,
        "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
        "-color_trc", "bt709", "-color_primaries", "bt709", "-color_range", "tv",
        "-r", "30", "-fps_mode", "cfr", "-field_order", "tb",
    ])
    if video_encoder == "libx265":
        blend_command.extend(["-flags:v", "+ilme+ildct"])
    blend_command.extend([
        "-video_track_timescale", "15360", "-c:a", "aac", "-b:a", "72k",
        "-ac", "2", "-ar", "44100", "-metadata",
        f"creation_time={creation_time}", "-metadata", "encoder=vcodec2",
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
