"""千川处理 · 漫落惊鸿通道。"""

import os
import random
import secrets
import shutil
import subprocess
from pathlib import Path

from core.build_config import BASE_DIR
from modes.base_mode import BaseMode


class ModeManluoJinghong(BaseMode):
    id = "duoduo/manluo_jinghong"
    name = "漫落惊鸿"
    sort_priority = -200
    platform = "duoduo"
    needs_aux = False
    gpu_supported = False
    supports_dedup_strength = True
    output_suffix = "_漫落惊鸿"
    output_naming = "source"
    ext = "mp4"
    help_text = "千川处理 · 漫落惊鸿（中度/重度去重）"

    @staticmethod
    def _stop_process(proc):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
            )
        else:
            proc.kill()

    def process(self, state, source, final_base, ffmpeg, use_gpu=False,
                on_log=None, on_progress=None, should_stop=None):
        strength = str((state or {}).get("dedup_mode") or "中度")
        if strength not in ("中度", "重度"):
            raise ValueError("去重强度只能是中度或重度")

        noises = Path(BASE_DIR) / "resources" / "tianqiong" / "noises"
        if not noises.is_dir() or not any(
            path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}
            for path in noises.rglob("*")
        ):
            raise RuntimeError("漫落惊鸿环境音频未打包")

        if strength == "中度":
            from . import tianqiong_medium as pipeline
            stage_total = 8
        else:
            from . import tianqiong_heavy as pipeline
            stage_total = 11

        ffmpeg_path = Path(ffmpeg)
        ffprobe = ffmpeg_path.with_name("ffprobe" + ffmpeg_path.suffix)
        if not ffprobe.is_file():
            found = shutil.which("ffprobe")
            if not found:
                raise RuntimeError("未找到 FFprobe")
            ffprobe = Path(found)

        completed = 0

        def run_process(command):
            nonlocal completed
            if Path(str(command[0])).stem.lower() == "ffprobe":
                return subprocess.check_output(
                    command, stderr=subprocess.STDOUT, creationflags=0x08000000 if os.name == "nt" else 0
                )
            if on_log:
                on_log("$ " + subprocess.list2cmdline([str(part) for part in command]))
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                if should_stop and should_stop():
                    self._stop_process(proc)
                    raise RuntimeError("已停止")
                if on_log and line.strip():
                    on_log(line.rstrip())
            code = proc.wait()
            if code:
                raise subprocess.CalledProcessError(code, command)
            completed += 1
            if on_progress:
                on_progress(min(95.0, completed * 95.0 / stage_total))
            return b""

        pipeline.ROOT = noises.parent
        pipeline.FFMPEG = ffmpeg_path
        pipeline.FFPROBE = ffprobe
        pipeline.run_process = run_process
        target = Path(f"{final_base}_{strength}.mp4")
        seed = secrets.randbits(63)
        pipeline.make_variant(Path(source), target, random.Random(seed), seed, None, False)
        if on_progress:
            on_progress(100.0)
        return [str(target)]


MODE = ModeManluoJinghong
