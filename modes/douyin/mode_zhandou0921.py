"""抖音疏影通道。"""

import subprocess
from pathlib import Path

from modes.douyin.mode_a1_worker import build_command, probe, resolve_tool
from modes.base_mode import BaseMode
from modes.douyin.hevc_gpu import select_hevc_encoder


class ModeZhandou0921(BaseMode):
    id = "douyin/zhandou0921"
    name = "疏影"
    platform = "douyin"
    needs_aux = False
    gpu_supported = True
    output_suffix = "_zhandou0921"
    output_naming = "source"
    ext = "mp4"
    help_text = "抖音处理 · 疏影（CPU / NVIDIA / AMD）"

    def has_gpu_command(self):
        return True

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        source = Path(main_video or (state or {}).get("main_video") or "")
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source

        try:
            if use_gpu is None:
                use_gpu = bool((state or {}).get("use_gpu"))
            encoder, encoder_options, gpu_error = select_hevc_encoder(state, use_gpu)
            if gpu_error:
                return "", bool(use_gpu), gpu_error
            root = Path(__file__).resolve().parents[2]
            reference = probe(resolve_tool(root, "ffprobe.exe"), source)
            params = self.build_params(state or {}, str(source), None)
            destination = Path(str(out_base or params["output"]) + "." + self.ext)
            command = build_command(
                "ffmpeg", source, destination, reference, int(params["threads"]),
                encoder, encoder_options,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return "", bool(use_gpu), "疏影参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""


MODE = ModeZhandou0921()
