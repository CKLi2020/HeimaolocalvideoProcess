"""千川处理 · 刹夜黑五通道。"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from core.build_config import BASE_DIR
from engine.mp4_metadata import write_randomized_metadata
from engine.native_core import core
from modes.base_mode import BaseMode


AUDIO_CHINESE = "汉语方言"
AUDIO_UNIVERSAL = "全语种"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_HIDDEN = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _probe(path: Path, ffprobe: Path) -> dict:
    return json.loads(subprocess.check_output([
        str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
    ], stderr=subprocess.STDOUT, **_HIDDEN).decode("utf-8", "replace"))


def _media_info(path: Path, ffprobe: Path) -> tuple[float, int, dict]:
    data = _probe(path, ffprobe)
    audio = next((item for item in data.get("streams", []) if item.get("codec_type") == "audio"), None)
    video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("主视频没有视频流")
    return (
        float(data.get("format", {}).get("duration") or 0),
        int(audio.get("channels") or 0) if audio else 0,
        video,
    )


def _run(command, duration=0.0, on_log=None, on_progress=None, should_stop=None):
    if on_log:
        on_log("$ " + subprocess.list2cmdline([str(part) for part in command]))
    proc = subprocess.Popen(
        [str(part) for part in command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **_HIDDEN,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if should_stop and should_stop():
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_HIDDEN)
                else:
                    proc.kill()
                raise RuntimeError("已停止")
            text = line.strip()
            if text.startswith(("out_time_us=", "out_time_ms=")) and duration > 0 and on_progress:
                value = text.partition("=")[2]
                if value.isdigit():
                    on_progress(min(100.0, int(value) / (duration * 10000.0)))
            elif text and on_log and not text.startswith(("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time", "dup_frames=", "drop_frames=", "speed=", "progress=")):
                on_log(text)
        code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if code:
        raise subprocess.CalledProcessError(code, command)


def _effect_window(duration: float) -> tuple[int, int]:
    total = max(12, int(duration * 30))
    start = random.randint(1, min(10, total - 3))
    return start, random.randint(max(start + 2, total * 2 // 3), max(start + 2, total - 1))


def _audio_filter(mode: str, channels: int) -> str:
    if mode == AUDIO_CHINESE:
        return core.qianchuan_audio_filter(channels).replace(
            ",pan=5.1|", ",asetpts=PTS+random(0.002)-0.001,pan=5.1|", 1,
        )
    if mode == AUDIO_UNIVERSAL:
        right = "c0" if channels == 1 else "c1"
        return (
            f"[0:a:0]aresample=44100,pan=stereo|c0=c0|c1={right},"
            "asetpts=PTS+random(0.004)-0.002[audio_in];"
            "anoisesrc=color=white:amplitude=0.003:sample_rate=44100,"
            "aformat=channel_layouts=stereo[noise];"
            "[audio_in][noise]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=level_in=1:limit=0.98:attack=5:release=50:level=false,"
            "dynaudnorm=f=50:g=3:p=0.7,"
            "pan=mono|c0=0.7071*c0+0.7071*c1[aout]"
        )
    raise ValueError("不支持的伪装语言：" + mode)


def _base_command(ffmpeg: Path, source: Path, target: Path, duration: float, channels: int,
                  state: dict, cover: Path | None = None):
    start, end = _effect_window(duration)
    flash = int(state.get("shaye_flash_value", 5)) if state.get("shaye_flash_enabled") else 10
    video_filter = core.qianchuan_filter(start, end, flash)
    inputs = ["-i", source]
    if cover:
        inputs += ["-i", cover]
        video_filter = (
            video_filter.replace("[outv]", "[processed]")
            + ";[1:v][processed]scale2ref[cover][base];"
              "[base][cover]overlay=eof_action=pass:enable='eq(n,0)'[outv]"
        )
    audio_args = []
    if channels:
        if state.get("shaye_audio_enabled", True):
            mode = str(state.get("shaye_audio_mode") or AUDIO_CHINESE)
            if mode == AUDIO_CHINESE:
                audio_args = ["-map", "0:a:0", "-af", _audio_filter(mode, channels),
                              "-c:a", "aac", "-profile:a", "aac_low", "-ar", "88200", "-ac", "6", "-b:a", "320k"]
            else:
                video_filter += ";" + _audio_filter(mode, channels)
                audio_args = ["-map", "[aout]", "-c:a", "aac", "-profile:a", "aac_low",
                              "-ar", "44100", "-ac", "1", "-b:a", "128k"]
        else:
            audio_args = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "194k", "-ar", "44100", "-ac", "2"]
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1",
        *inputs, "-filter_complex", video_filter, "-map", "[outv]", *audio_args,
        "-c:v", "libx264", "-preset", "fast", "-b:v", "17125k", "-maxrate", "17125k",
        "-bufsize", "34250k", "-threads:v", "2", "-pix_fmt", "yuv420p", "-profile:v", "main",
        "-level:v", "5.1", "-bf", "2", "-refs", "1", "-g", "250", "-keyint_min", "250",
        "-sc_threshold", "0", "-fps_mode", "cfr", "-r", "120", "-video_track_timescale", "15360",
        "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", target,
    ]


def _fission_command(ffmpeg: Path, source: Path, target: Path, recipe: dict,
                     has_audio: bool, cover: Path | None = None):
    bitrate = int(recipe["target_bitrate_kbps"])
    audio = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] if has_audio else []
    inputs = ["-i", source]
    video_filter = core.qianchuan_fission_filter(recipe)
    if cover:
        inputs += ["-i", cover]
        video_filter = (
            f"[0:v:0]{video_filter}[processed];"
            "[1:v:0][processed]scale2ref[cover][base];"
            "[base][cover]overlay=eof_action=pass:enable='eq(n,0)'[outv]"
        )
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1",
        *inputs, "-map", "[outv]" if cover else "0:v:0",
        "-filter_complex" if cover else "-vf", video_filter, *audio,
        "-c:v", "libx264", "-b:v", f"{bitrate}k", "-preset", "slow", "-maxrate", f"{bitrate}k",
        "-bufsize", f"{bitrate * 2}k", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", target,
    ]


def _face_blur(source: Path, target: Path, ffmpeg: Path, state: dict, on_log, should_stop):
    from engine.face_blur import FaceBlurEngine

    raw = target.with_name(target.stem + "_raw.mp4")
    blur = FaceBlurEngine(
        blur_strength=int(state.get("shaye_face_strength", 10)),
        blur_expand=int(state.get("shaye_face_expand", 30)),
        detect_every=int(state.get("shaye_face_every", 5)),
        log_callback=on_log,
    )
    try:
        if not blur.process_video(source, raw, cancel_check=should_stop):
            raise RuntimeError("人脸遮挡处理失败")
        if should_stop and should_stop():
            raise RuntimeError("已停止")
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", raw, "-i", source,
              "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
              "-c:a", "copy", "-shortest", target], on_log=on_log, should_stop=should_stop)
    finally:
        raw.unlink(missing_ok=True)


def _verify_timestamps(path: Path, ffprobe: Path, flash: int):
    data = json.loads(subprocess.check_output([
        str(ffprobe), "-v", "error", "-read_intervals", "0%+0.5", "-select_streams", "v:0",
        "-show_packets", "-show_entries", "packet=pts_time,flags", "-of", "json", str(path),
    ], stderr=subprocess.STDOUT, **_HIDDEN).decode("utf-8", "replace"))
    if not core.qianchuan_verify_timestamps(data.get("packets", []), flash):
        raise RuntimeError("输出时间戳校验失败")


def _output_path(folder: Path, source: Path) -> Path:
    while True:
        target = folder / f"{source.stem}_{random.randint(100000, 999999)}.mp4"
        if not target.exists():
            return target


@contextmanager
def _secure_temporary_directory(parent: Path):
    root = Path(tempfile.mkdtemp(prefix=".temp_shaye_", dir=str(parent)))
    try:
        yield root
    finally:
        for path in sorted(root.rglob("*"), reverse=True):
            if not path.is_file():
                continue
            try:
                with path.open("r+b") as stream:
                    remaining = path.stat().st_size
                    zeroes = b"\0" * min(4 * 1024 * 1024, max(1, remaining))
                    while remaining:
                        block = zeroes[:min(len(zeroes), remaining)]
                        stream.write(block)
                        remaining -= len(block)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)


def _patch_timeline(path: Path, hours: float, ffmpeg: Path, on_log, should_stop):
    if not 0.1 <= hours <= 2.0:
        raise ValueError("伪装时长必须在 0.1 到 2.0 小时之间")
    tool = Path(BASE_DIR) / "resources" / "tools" / "patch-nightcat-v7-timeline.exe"
    if not tool.is_file():
        raise RuntimeError("缺少 MP4 时间轴工具：" + str(tool))
    normalized = path.with_name(path.stem + ".timeline-ready.mp4")
    try:
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-map", "0:v:0",
              "-map", "0:a?", "-c", "copy", "-movflags", "+faststart", normalized],
             on_log=on_log, should_stop=should_stop)
        normalized.replace(path)
        _run([tool, path, "--target-hours", f"{hours:.12g}"], on_log=on_log, should_stop=should_stop)
    finally:
        normalized.unlink(missing_ok=True)


class ModeShayeHeiw(BaseMode):
    id = "duoduo/shaye_heiw"
    name = "刹夜黑五"
    sort_priority = -300
    platform = "duoduo"
    needs_aux = False
    gpu_supported = False
    supports_copies = True
    supports_shaye_options = True
    output_suffix = "_刹夜黑五"
    output_naming = "source"
    ext = "mp4"
    help_text = "千川处理 · 刹夜黑五（闪动、音频伪装、人脸遮挡、裂变与时间轴处理）"

    @staticmethod
    def output_count(state):
        return max(1, min(100, int((state or {}).get("copies", 1))))

    def process(self, state, source, final_base, ffmpeg, use_gpu=False,
                on_log=None, on_progress=None, should_stop=None):
        state = state or {}
        source = Path(source)
        ffmpeg = Path(ffmpeg)
        ffprobe = ffmpeg.with_name("ffprobe" + ffmpeg.suffix)
        if not source.is_file():
            raise ValueError("输入视频不存在：" + str(source))
        if not ffprobe.is_file():
            found = shutil.which("ffprobe")
            if not found:
                raise RuntimeError("未找到 FFprobe")
            ffprobe = Path(found)

        duration, channels, _video = _media_info(source, ffprobe)
        cover_text = str(state.get("shaye_cover") or "").strip()
        cover = Path(cover_text) if cover_text else None
        if cover and (not cover.is_file() or cover.suffix.lower() not in IMAGE_EXTS):
            raise ValueError("请选择有效的首图图片（JPG、PNG、WEBP 或 BMP）")
        copies = self.output_count(state)
        flash = int(state.get("shaye_flash_value", 5)) if state.get("shaye_flash_enabled") else 10
        outputs = []
        targets = []
        parent = Path(final_base).parent
        try:
            with _secure_temporary_directory(parent) as temp:
                processing_source = source
                if state.get("shaye_face_enabled", True):
                    processing_source = temp / "face.mp4"
                    _face_blur(source, processing_source, ffmpeg, state, on_log, should_stop)

                base = temp / "base.mp4"
                _run(_base_command(ffmpeg, processing_source, base, duration, channels, state, cover), duration,
                     on_log, lambda value: on_progress(value * 0.6) if on_progress else None, should_stop)
                _verify_timestamps(base, ffprobe, flash)

                for index in range(copies):
                    if should_stop and should_stop():
                        raise RuntimeError("已停止")
                    target = _output_path(parent, source)
                    targets.append(target)
                    if index == 0:
                        shutil.copy2(base, target)
                    else:
                        _, has_audio, video = _media_info(base, ffprobe)
                        rate = str(video.get("r_frame_rate") or "0/1")
                        top, bottom = rate.split("/", 1) if "/" in rate else (rate, "1")
                        bitrate = int(video.get("bit_rate") or 0)
                        if bitrate <= 0:
                            bitrate = int(_probe(base, ffprobe).get("format", {}).get("bit_rate") or 0)
                        recipe = core.qianchuan_fission_recipe(
                            bitrate, float(top) / float(bottom), int(video.get("width") or 0), int(video.get("height") or 0),
                        )
                        _run(_fission_command(ffmpeg, base, target, recipe, bool(has_audio), cover), duration,
                             on_log, None, should_stop)
                    if state.get("shaye_fake_duration_enabled"):
                        _patch_timeline(target, float(state.get("shaye_fake_hours", 1.9)), ffmpeg, on_log, should_stop)
                    write_randomized_metadata(target)
                    outputs.append(str(target))
                    if on_progress:
                        on_progress(60.0 + 40.0 * (index + 1) / copies)
        except BaseException:
            for target in targets:
                target.unlink(missing_ok=True)
            raise
        return outputs


MODE = ModeShayeHeiw()
