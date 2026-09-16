"""Standalone recovery of the original app's video-account ``sph4`` mode.

The FFmpeg pipeline and fixed values in this file were recovered from the
decrypted command retained by the running, authorized original application on
2026-09-16.  No network connection or login is required to run this file.
"""

from __future__ import annotations

import argparse
import random
import shutil
import subprocess
import sys
from pathlib import Path


VIDEO_FILTER = (
    "[0:v]fps=30,"
    "scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,"
    "crop=720:1280:(iw-ow)/2:(ih-oh)/2,"
    "setsar=32102/29837,format=yuv420p[v];"
    "[0:a]aresample=44100,aformat=channel_layouts=stereo,"
    "asplit=2[aorig][arevsrc];"
    "[arevsrc]areverse,asetpts=PTS-STARTPTS,"
    "aformat=channel_layouts=stereo[arev]"
)


METADATA = (
    "title=ULTIMATE_ORIGINAL_CONTENT_405514628",
    "artist=Panasonic S5_CREATOR_98295",
    "album=ORIGINAL_COLLECTION_1874",
    "date=2026",
    "encoding_tool=Wxmm_9020230808",
    "comment=ORIGINAL_PROCESSED_63945655",
    "genre=CREATIVE_ORIGINAL_CONTENT_717800",
    "copyright=CREATOR_ORIGINAL_6752715",
    "description=UNIQUE_ORIGINAL_WORK_48874711",
    "track=388",
    "make=Canon",
    "model=EOS R8",
    "location=+22.5965+114.5077/",
    "location-eng=+22.5965+114.5077/",
    "location_name=较场尾",
    "capture_period=2026-06-21",
    "capture_date=2026-06-21",
    "metadata_status=restored/inferred",
)


def find_ffmpeg(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(f"FFmpeg 不存在: {candidate}")

    here = Path(__file__).resolve().parent
    candidates = (
        here / "bin" / "ffmpeg.exe",
        here.parent / "bin" / "ffmpeg.exe",
        Path(shutil.which("ffmpeg") or ""),
    )
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("未找到 ffmpeg.exe；请使用 --ffmpeg 指定路径")


def build_command(
    ffmpeg: Path,
    source: Path,
    destination: Path,
    silent_duration: int,
) -> list[str]:
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-loglevel",
        "warning",
        "-stats",
        "-stats_period",
        "0.5",
        "-i",
        str(source),
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=channel_layout=mono:sample_rate=8000:d={silent_duration}",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-lavfi",
        VIDEO_FILTER,
        "-map",
        "[v]",
        "-map",
        "[aorig]",
        "-map",
        "[arev]",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-b:v",
        "2098k",
        "-maxrate",
        "2098k",
        "-bufsize",
        "4196k",
        "-x264-params",
        "ref=1:bframes=2",
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
        "-r",
        "30",
        "-video_track_timescale",
        "15360",
        "-c:a:0",
        "aac",
        "-b:a:0",
        "124k",
        "-ar:a:0",
        "44100",
        "-ac:a:0",
        "2",
        "-c:a:1",
        "aac",
        "-b:a:1",
        "124k",
        "-ar:a:1",
        "44100",
        "-ac:a:1",
        "2",
        "-c:a:2",
        "aac",
        "-b:a:2",
        "8k",
        "-ar:a:2",
        "8000",
        "-ac:a:2",
        "1",
        "-disposition:a:0",
        "default",
        "-disposition:a:1",
        "0",
        "-disposition:a:2",
        "0",
        "-metadata:s:a:0",
        "title=Phone_Normal_Default",
        "-metadata:s:a:1",
        "title=Local_Full_Reverse_Optional",
        "-metadata:s:a:2",
        "title=Silent_Market_3_8H",
    ]
    for item in METADATA:
        command.extend(("-metadata", item))
    command.extend(
        (
            "-metadata:s:v:0",
            "handler_name=VideoHandler",
            "-metadata:s:a:0",
            "handler_name=SoundHandler",
            "-brand",
            "isom",
            "-movflags",
            "+faststart+use_metadata_tags",
            "-f",
            "mp4",
            str(destination),
        )
    )
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="小花猫视频号 sph4 通道的独立本地处理器"
    )
    parser.add_argument("input", type=Path, help="输入视频")
    parser.add_argument("output", nargs="?", type=Path, help="输出 MP4")
    parser.add_argument("--ffmpeg", help="ffmpeg.exe 的完整路径")
    parser.add_argument(
        "--silent-duration",
        type=int,
        help="第三音轨时长（秒）；默认按原通道随机 10800..28800",
    )
    parser.add_argument("--dry-run", action="store_true", help="只显示参数，不执行")
    return parser.parse_args()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"输入视频不存在: {source}")

    destination = (
        args.output.expanduser().resolve()
        if args.output
        else source.with_name(f"{source.stem}_sph4.mp4")
    )
    if destination == source:
        raise ValueError("输出路径不能与输入视频相同")
    destination.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(args.ffmpeg)
    duration = (
        random.randint(10800, 28800)
        if args.silent_duration is None
        else args.silent_duration
    )
    if not 1 <= duration <= 86400:
        raise ValueError("--silent-duration 必须在 1..86400 之间")

    command = build_command(ffmpeg, source, destination, duration)
    if args.dry_run:
        print(subprocess.list2cmdline(command))
        return 0

    print(f"输入: {source}")
    print(f"输出: {destination}")
    print(f"长静音轨: {duration} 秒")
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        print(f"FFmpeg 处理失败，退出码 {completed.returncode}", file=sys.stderr)
        return completed.returncode
    if not destination.is_file() or destination.stat().st_size == 0:
        print("处理失败：输出文件缺失或为空", file=sys.stderr)
        return 2
    print(f"处理完成: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
