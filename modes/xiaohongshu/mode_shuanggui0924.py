"""小红书折枝通道0924。"""

import subprocess
from pathlib import Path

from modes.xiaohongshu.mode_xiaohongshu_shuanggui_worker import build_command
from modes.base_mode import BaseMode
from modes.shipinhao.h264_gpu import select_h264_encoder


class ModeShuanggui0924(BaseMode):
    id = "xiaohongshu/shuanggui0924"
    name = "折枝通道0924"
    platform = "xiaohongshu"
    needs_aux = False
    gpu_supported = True
    output_suffix = "_shuanggui0924"
    output_naming = "source"
    ext = "mp4"
    help_text = "小红书处理 · 折枝通道0924（单主视频，CPU / NVIDIA / AMD）"

    def has_gpu_command(self):
        return True

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        source = Path(main_video or (state or {}).get("main_video") or "")
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source

        if use_gpu is None:
            use_gpu = bool((state or {}).get("use_gpu"))
        try:
            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return "", bool(use_gpu), gpu_error
            params = self.build_params(state or {}, str(source))
            destination = Path(str(out_base or params["output"]) + "." + self.ext)
            command = build_command(
                "ffmpeg", source, destination, int(params["threads"]),
                encoder, encoder_options, "yuv420p" if use_gpu else None,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return "", bool(use_gpu), "折枝通道参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""


MODE = ModeShuanggui0924()