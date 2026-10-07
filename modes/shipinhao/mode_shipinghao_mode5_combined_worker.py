import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from engine.native_core import core as _native_core

SWITCH_MODES = {
    "daoli": "shipinghao_mode5_daolimoshi",
    "lasong": "shipinghao_mode5_lasong",
    "ronghe": "shipinghao_mode5_ronghe",
}
CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}
VERTICAL_FLIP_MATRIX = (65536, 0, 0, 0, -65536, 0, 0, 0, 1073741824)
UNKNOWN_TRANSFORMATIONS = {
    "daoli": "The captured raw-video decoder applies vflip; the output also has a vertical-flip MP4 display matrix. Additional in-application raw-frame changes are not inferred from this evidence.",
    "lasong": "The captured main-input sample confirms BT.709/TV signaling and a centered 576x1024 image with 112-pixel padding; unobserved source-aspect-ratio behavior is not certified.",
    "ronghe": "Fusion was captured with the main input used as its own auxiliary at 50% opacity. This cannot prove the external application's general two-source blending implementation.",
}
STREAM_FIELDS = (
    "index",
    "codec_name",
    "profile",
    "codec_type",
    "codec_tag_string",
    "width",
    "height",
    "has_b_frames",
    "sample_aspect_ratio",
    "display_aspect_ratio",
    "pix_fmt",
    "level",
    "color_range",
    "color_space",
    "color_transfer",
    "color_primaries",
    "chroma_location",
    "field_order",
    "r_frame_rate",
    "avg_frame_rate",
    "time_base",
    "start_time",
    "duration",
    "nb_frames",
    "nb_read_packets",
    "sample_fmt",
    "sample_rate",
    "channels",
    "channel_layout",
)
STREAM_TAGS = ("language", "handler_name", "vendor_id", "encoder")
FORMAT_FIELDS = ("nb_streams", "nb_programs", "format_name", "start_time", "duration")
FORMAT_TAGS = ("major_brand", "minor_version", "compatible_brands", "encoder")


class WorkerError(RuntimeError):
    pass


def resolve_tool(name: str, script_directory: Path) -> Path:
    candidates = (script_directory / "bin" / name, script_directory / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    resolved = shutil.which(name)
    if resolved:
        return Path(resolved)
    raise WorkerError(f"Unable to locate {name} in bin/, the script directory, or PATH.")


def run(command: list[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
    )


def iter_boxes(data: bytes, start: int = 0, end: Optional[int] = None):
    end = len(data) if end is None else end
    offset = start
    while offset + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, offset)
        header_size = 8
        if size == 1:
            if offset + 16 > end:
                raise WorkerError("Truncated extended MP4 box header.")
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header_size = 16
        elif size == 0:
            size = end - offset
        if size < header_size or offset + size > end:
            raise WorkerError(f"Invalid MP4 box {kind!r} at offset {offset}.")
        yield kind, offset, size, header_size
        offset += size
    if offset != end:
        raise WorkerError(f"Unparsed MP4 bytes at offset {offset}.")


def make_box(kind: bytes, payload: bytes) -> bytes:
    size = len(payload) + 8
    if size >= 2**32:
        return struct.pack(">I4sQ", 1, kind, len(payload) + 16) + payload
    return struct.pack(">I4s", size, kind) + payload


def find_descendant(data: bytes, wanted: bytes) -> Optional[tuple[int, int, int]]:
    for kind, offset, size, header_size in iter_boxes(data):
        if kind == wanted:
            return offset, size, header_size
        if kind in CONTAINER_BOXES:
            child = find_descendant(data[offset + header_size : offset + size], wanted)
            if child:
                child_offset, child_size, child_header = child
                return offset + header_size + child_offset, child_size, child_header
    return None


def track_handler(track: bytes) -> bytes:
    hdlr = find_descendant(track, b"hdlr")
    if not hdlr:
        raise WorkerError("MP4 track has no hdlr box.")
    offset, _, header_size = hdlr
    payload = offset + header_size
    if payload + 12 > len(track):
        raise WorkerError("Truncated MP4 hdlr box.")
    return track[payload + 8 : payload + 12]


def parse_run_table(box: bytes, signed_values: bool = False) -> tuple[int, list[tuple[int, int]]]:
    header_size = 16 if struct.unpack_from(">I", box, 0)[0] == 1 else 8
    version = box[header_size]
    entry_count = struct.unpack_from(">I", box, header_size + 4)[0]
    cursor = header_size + 8
    entries: list[tuple[int, int]] = []
    value_format = ">i" if signed_values else ">I"
    for _ in range(entry_count):
        if cursor + 8 > len(box):
            raise WorkerError("Truncated MP4 timing table.")
        count = struct.unpack_from(">I", box, cursor)[0]
        value = struct.unpack_from(value_format, box, cursor + 4)[0]
        entries.append((count, value))
        cursor += 8
    return version, entries


def expanded_values(entries: list[tuple[int, int]]) -> list[int]:
    values: list[int] = []
    for count, value in entries:
        values.extend([value] * count)
    return values


def timing_replacements(track: bytes, flip: bool) -> dict[bytes, bytes]:
    stts_location = find_descendant(track, b"stts")
    ctts_location = find_descendant(track, b"ctts")
    if not stts_location or not ctts_location:
        raise WorkerError("Video track must contain both stts and ctts boxes.")

    stts_offset, stts_size, _ = stts_location
    ctts_offset, ctts_size, _ = ctts_location
    stts_box = track[stts_offset : stts_offset + stts_size]
    ctts_box = track[ctts_offset : ctts_offset + ctts_size]
    _, stts_entries = parse_run_table(stts_box)
    ctts_version, ctts_entries = parse_run_table(ctts_box, signed_values=ctts_box[8] == 1)
    deltas = expanded_values(stts_entries)
    offsets = expanded_values(ctts_entries)
    if len(deltas) != len(offsets):
        raise WorkerError("Video stts and ctts sample counts differ.")
    if any(delta <= 0 for delta in deltas):
        raise WorkerError("Video stts contains a non-positive sample delta.")
    if ctts_version not in (0, 1):
        raise WorkerError(f"Unsupported ctts version {ctts_version}.")

    doubled_stts = bytearray(b"\x00\x00\x00\x00" + struct.pack(">I", len(stts_entries)))
    for count, delta in stts_entries:
        doubled_stts.extend(struct.pack(">II", count, delta * 2))

    rewritten_offsets: list[int] = []
    added_decode_time = 0
    for delta, offset in zip(deltas, offsets):
        rewritten_offset = offset - added_decode_time
        if not -(2**31) <= rewritten_offset < 2**31:
            raise WorkerError("Rewritten ctts offset exceeds signed 32-bit range.")
        rewritten_offsets.append(rewritten_offset)
        added_decode_time += delta

    rewritten_ctts = bytearray(b"\x01\x00\x00\x00" + struct.pack(">I", len(rewritten_offsets)))
    for offset in rewritten_offsets:
        rewritten_ctts.extend(struct.pack(">Ii", 1, offset))

    replacements = {
        b"stts": make_box(b"stts", bytes(doubled_stts)),
        b"ctts": make_box(b"ctts", bytes(rewritten_ctts)),
    }
    if flip:
        tkhd_location = find_descendant(track, b"tkhd")
        if not tkhd_location:
            raise WorkerError("Video track must contain a tkhd box.")
        tkhd_offset, tkhd_size, tkhd_header = tkhd_location
        tkhd_box = bytearray(track[tkhd_offset : tkhd_offset + tkhd_size])
        tkhd_version = tkhd_box[tkhd_header]
        if tkhd_version not in (0, 1):
            raise WorkerError(f"Unsupported tkhd version {tkhd_version}.")
        matrix_offset = tkhd_header + 4 + (36 if tkhd_version == 0 else 48)
        struct.pack_into(">9i", tkhd_box, matrix_offset, *VERTICAL_FLIP_MATRIX)
        replacements[b"tkhd"] = bytes(tkhd_box)
    return replacements


def shift_chunk_offsets(box: bytes, shift: int) -> bytes:
    size32, kind = struct.unpack_from(">I4s", box, 0)
    header_size = 16 if size32 == 1 else 8
    payload = bytearray(box[header_size:])
    entry_count = struct.unpack_from(">I", payload, 4)[0]
    width = 4 if kind == b"stco" else 8
    value_format = ">I" if width == 4 else ">Q"
    cursor = 8
    for _ in range(entry_count):
        value = struct.unpack_from(value_format, payload, cursor)[0]
        shifted = value + shift
        if shifted < 0 or shifted >= 2 ** (width * 8):
            raise WorkerError("Shifted MP4 chunk offset is out of range.")
        struct.pack_into(value_format, payload, cursor, shifted)
        cursor += width
    return make_box(kind, bytes(payload))


def rewrite_container(
    container: bytes,
    chunk_shift: int,
    flip: bool,
    video_timing: Optional[dict[bytes, bytes]] = None,
) -> bytes:
    size32, kind = struct.unpack_from(">I4s", container, 0)
    header_size = 16 if size32 == 1 else 8
    payload = container[header_size:]
    rebuilt = bytearray()
    for child_kind, offset, size, _ in iter_boxes(payload):
        child = payload[offset : offset + size]
        if child_kind == b"trak":
            replacements = timing_replacements(child, flip) if track_handler(child) == b"vide" else None
            child = rewrite_container(child, chunk_shift, flip, replacements)
        elif child_kind in CONTAINER_BOXES:
            child = rewrite_container(child, chunk_shift, flip, video_timing)
        elif video_timing and child_kind in video_timing:
            child = video_timing[child_kind]
        elif child_kind in {b"stco", b"co64"} and chunk_shift:
            child = shift_chunk_offsets(child, chunk_shift)
        rebuilt.extend(child)
    return make_box(kind, bytes(rebuilt))


def rewrite_timing(source: Path, destination: Path, flip: bool) -> None:
    data = source.read_bytes()
    top_level = list(iter_boxes(data))
    moov = next((box for box in top_level if box[0] == b"moov"), None)
    mdat = next((box for box in top_level if box[0] == b"mdat"), None)
    if not moov or not mdat:
        raise WorkerError("Encoded output must contain moov and mdat boxes.")
    _, moov_offset, moov_size, _ = moov
    _, mdat_offset, _, _ = mdat
    if moov_offset > mdat_offset:
        raise WorkerError("Encoded output is not faststart; moov must precede mdat.")

    original_moov = data[moov_offset : moov_offset + moov_size]
    preliminary_moov = rewrite_container(original_moov, 0, flip)
    chunk_shift = len(preliminary_moov) - len(original_moov)
    rewritten_moov = rewrite_container(original_moov, chunk_shift, flip)
    if len(rewritten_moov) - len(original_moov) != chunk_shift:
        raise WorkerError("MP4 timing rewrite changed size during offset correction.")

    destination.write_bytes(
        data[:moov_offset] + rewritten_moov + data[moov_offset + moov_size :]
    )


def probe(ffprobe: Path, media: Path) -> dict[str, Any]:
    command = [
        str(ffprobe),
        "-v",
        "error",
        "-count_packets",
        "-show_streams",
        "-show_format",
        "-show_programs",
        "-show_chapters",
        "-of",
        "json",
        str(media),
    ]
    result = run(command, capture_output=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise WorkerError(f"ffprobe returned invalid JSON for {media}: {error}") from error


def normalized_signature(probe_data: dict[str, Any]) -> dict[str, Any]:
    streams = []
    for stream in probe_data.get("streams", []):
        signature = {field: stream.get(field) for field in STREAM_FIELDS}
        signature["disposition"] = stream.get("disposition", {})
        tags = stream.get("tags", {})
        signature["tags"] = {field: tags.get(field) for field in STREAM_TAGS}
        signature["display_matrices"] = [
            {
                field: side_data[field]
                for field in ("side_data_type", "displaymatrix", "rotation")
                if field in side_data
            }
            for side_data in stream.get("side_data_list", [])
            if side_data.get("side_data_type") == "Display Matrix"
        ]
        streams.append(signature)

    media_format = probe_data.get("format", {})
    format_signature = {field: media_format.get(field) for field in FORMAT_FIELDS}
    format_tags = media_format.get("tags", {})
    format_signature["tags"] = {field: format_tags.get(field) for field in FORMAT_TAGS}
    chapters = [
        {
            "id": chapter.get("id"),
            "time_base": chapter.get("time_base"),
            "start": chapter.get("start"),
            "end": chapter.get("end"),
            "tags": chapter.get("tags", {}),
        }
        for chapter in probe_data.get("chapters", [])
    ]
    return {"streams": streams, "format": format_signature, "chapters": chapters}


def compare_values(expected: Any, actual: Any, path: str = "") -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            child_path = f"{path}.{key}" if path else key
            if key not in expected or key not in actual:
                differences.append(
                    {"path": child_path, "expected": expected.get(key), "actual": actual.get(key)}
                )
            else:
                differences.extend(compare_values(expected[key], actual[key], child_path))
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            differences.append({"path": f"{path}.length", "expected": len(expected), "actual": len(actual)})
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            differences.extend(compare_values(expected_item, actual_item, f"{path}[{index}]"))
        return differences
    if path == "format.duration" and expected is not None and actual is not None:
        if abs(float(expected) - float(actual)) <= 0.001:
            return differences
    if expected != actual:
        differences.append({"path": path, "expected": expected, "actual": actual})
    return differences


def build_ffmpeg_command(
    ffmpeg: Path,
    input_path: Path,
    output_path: Path,
    *,
    auxiliary_path: Optional[Path] = None,
    video_encoder: str = "libx264",
    encoder_options: Sequence[str] = (),
    threads: int = 6,
    daoli: bool = False,
    lasong: bool = False,
    ronghe: bool = False,
    opacity: int = 50,
) -> list[str]:
    plan = _native_core.qixia_pipeline_plan(daoli, lasong, ronghe, opacity)
    inputs = ["-i", str(input_path)]
    if ronghe:
        inputs.extend(["-stream_loop", "-1", "-i", str(auxiliary_path or input_path)])
    color_options = (
        ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
        if lasong
        else []
    )
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        str(threads),
        *inputs,
        "-filter_complex",
        plan["filter_complex"],
        "-map",
        "[v]",
        "-map",
        "0:a:0",
        "-c:v",
        video_encoder,
    ]
    if video_encoder == "libx264":
        command.extend([
            "-preset",
            "medium",
            "-profile:v",
            "main",
            "-level",
            "3.2",
            "-bf",
            "3",
            "-refs",
            "4",
            "-g",
            "18",
            "-x264-params",
            plan["x264_params"],
        ])
    else:
        command.extend(encoder_options)
    command.extend([
        "-b:v",
        "9000k",
        "-pix_fmt",
        "yuv420p",
        *color_options,
        "-r",
        "60",
        "-video_track_timescale",
        "15360",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    return command


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Combined shipinghao_mode5 worker for the daoli, lasong, and ronghe switches.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--auxiliary", type=Path, help="optional auxiliary video used by the fusion switch")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ffmpeg", type=Path, help="explicit FFmpeg binary for reference comparisons")
    parser.add_argument("--ffprobe", type=Path, help="explicit ffprobe binary for reference comparisons")
    parser.add_argument("--opacity", type=int, default=50, help="fusion opacity, 0 to 100 (default: 50)")
    parser.add_argument("--daoli", action="store_true", help="倒立: vertical pixel flip plus vertical-flip display matrix")
    parser.add_argument("--lasong", action="store_true", help="拉伸: captured BT.709/TV color signaling")
    parser.add_argument("--ronghe", action="store_true", help="融合: captured base pipeline")
    args = parser.parse_args()

    switches = [name for name in SWITCH_MODES if getattr(args, name)]
    if not 0 <= args.opacity <= 100:
        parser.error("--opacity must be from 0 to 100")

    report_path = args.report or args.output.with_suffix(".comparison.json")
    report: dict[str, Any] = {
        "mode": (
            SWITCH_MODES[switches[0]] if len(switches) == 1
            else "shipinghao_mode5_" + ("+".join(switches) or "baseline")
        ),
        "switches": switches,
        "opacity": args.opacity,
        "input": str(args.input.resolve()),
        "reference": str(args.reference.resolve()),
        "auxiliary": str(args.auxiliary.resolve()) if args.auxiliary else None,
        "output": str(args.output.resolve()),
        "policy": {
            "format_duration_tolerance_seconds": 0.001,
            "excluded": [
                "file size",
                "CRF/CBR-derived bitrate",
                "whole-file hashes",
                "encoded packet bytes",
                "pixel hashes, SSIM, and PSNR",
                "volatile creation timestamps",
            ],
        },
        "passed": False,
    }

    encoded_path = args.output.with_name(args.output.name + ".encoding.mp4")
    try:
        if not args.input.is_file():
            raise WorkerError(f"Input does not exist: {args.input}")
        if not args.reference.is_file():
            raise WorkerError(f"Reference does not exist: {args.reference}")
        if args.auxiliary and not args.auxiliary.is_file():
            raise WorkerError(f"Auxiliary input does not exist: {args.auxiliary}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        script_directory = Path(__file__).resolve().parents[2]
        ffmpeg = args.ffmpeg or resolve_tool("ffmpeg.exe" if os.name == "nt" else "ffmpeg", script_directory)
        ffprobe = args.ffprobe or resolve_tool("ffprobe.exe" if os.name == "nt" else "ffprobe", script_directory)

        command = build_ffmpeg_command(
            ffmpeg,
            args.input.resolve(),
            encoded_path.resolve(),
            auxiliary_path=args.auxiliary.resolve() if args.auxiliary else None,
            daoli=args.daoli,
            lasong=args.lasong,
            ronghe=args.ronghe,
            opacity=args.opacity,
        )
        run(command)
        rewrite_timing(encoded_path, args.output, flip=args.daoli)
        encoded_path.unlink(missing_ok=True)

        expected = normalized_signature(probe(ffprobe, args.reference.resolve()))
        actual = normalized_signature(probe(ffprobe, args.output.resolve()))
        differences = compare_values(expected, actual)
        report.update(
            {
                "ffmpeg": str(ffmpeg),
                "ffprobe": str(ffprobe),
                "expected_signature": expected,
                "actual_signature": actual,
                "differences": differences,
                "passed": not differences,
                "unknown_transformations": [UNKNOWN_TRANSFORMATIONS[name] for name in switches],
            }
        )
        write_report(report_path, report)
        return 0 if not differences else 2
    except (OSError, subprocess.CalledProcessError, WorkerError, ValueError) as error:
        report["error"] = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            report["command"] = error.cmd
            report["stdout"] = error.stdout
            report["stderr"] = error.stderr
        write_report(report_path, report)
        return 1
    finally:
        encoded_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
