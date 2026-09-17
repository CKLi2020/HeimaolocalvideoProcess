"""视频号 sph4：从原程序运行时命令恢复的 CPU 通道。"""

import random
import subprocess
from pathlib import Path

from modes.base_mode import BaseMode
from shipinhao_sph4 import build_command


class ModeSph4(BaseMode):
    id = "shipinhao/sph4"
    name = "小花猫苍穹通道-2026-9-16更新"
    platform = "shipinhao"
    needs_aux = False
    gpu_supported = False
    output_suffix = "_sph4"
    output_naming = "source"
    ext = "mp4"
    expected_audio_tracks = 3
    help_text = "视频号 sph4 原通道（CPU）"

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        source = Path(main_video or (state or {}).get("main_video") or "")
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source

        params = self.build_params(state or {}, str(source), None)
        destination = Path(str(out_base or params["output"]) + "." + self.ext)
        duration = int((state or {}).get("silent_duration") or random.randint(10800, 28800))
        command = build_command(Path("ffmpeg"), source, destination, duration)
        return subprocess.list2cmdline(command), False, ""


MODE = ModeSph4()
