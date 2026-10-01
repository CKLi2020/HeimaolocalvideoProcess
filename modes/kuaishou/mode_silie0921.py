"""快手长河通道。"""

import subprocess
from pathlib import Path

from modes.kuaishou.mode_kuai_ai_worker import build_command
from modes.base_mode import BaseMode
from modes.kuaishou.h264_gpu import select_h264_encoder


class ModeSilie0921(BaseMode):
    id = "kuaishou/silie0921"
    name = "长河"
    platform = "kuaishou"
    needs_aux = False
    gpu_supported = True
    output_suffix = "_silie0921"
    output_naming = "source"
    ext = "mkv"
    help_text = "快手处理 · 长河（CPU / NVIDIA / AMD）"

    def has_gpu_command(self):
        return True

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        source = Path(main_video or (state or {}).get("main_video") or "")
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source

        try:
            if use_gpu is None:
                use_gpu = bool((state or {}).get("use_gpu"))
            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return "", bool(use_gpu), gpu_error
            params = self.build_params(state or {}, str(source), None)
            destination = Path(str(out_base or params["output"]) + "." + self.ext)
            command = build_command(
                "ffmpeg", source, destination, int(params["threads"]),
                encoder, encoder_options,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return "", bool(use_gpu), "长河参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""


MODE = ModeSilie0921()
