"""快手冰峰财神通道0923。"""

import subprocess
from pathlib import Path

from modes.kuaishou.mode_kuaishou_binfeng_worker import build_command, probe, resolve_tool
from modes.base_mode import BaseMode
from modes.kuaishou.h264_gpu import select_h264_encoder


class ModeBinfengCaishen0923(BaseMode):
    id = "kuaishou/binfeng_caishen0923"
    name = "冰峰财神通道0923"
    platform = "kuaishou"
    needs_aux = True
    gpu_supported = True
    output_suffix = "_binfeng_caishen0923"
    output_naming = "source"
    ext = "mp4"
    help_text = "快手处理 · 冰峰财神通道0923（主视频 + 辅助视频，CPU / NVIDIA / AMD）"

    def has_gpu_command(self):
        return True

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        source = Path(main_video or (state or {}).get("main_video") or "")
        effect = Path(aux_video or (state or {}).get("aux_video") or "")
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source
        if not effect.is_file():
            return "", False, "辅视频不存在: %s" % effect

        try:
            if use_gpu is None:
                use_gpu = bool((state or {}).get("use_gpu"))
            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return "", bool(use_gpu), gpu_error
            root = Path(__file__).resolve().parents[2]
            reference = probe(resolve_tool(root, "ffprobe.exe"), source)
            params = self.build_params(state or {}, str(source), str(effect))
            destination = Path(str(out_base or params["output"]) + "." + self.ext)
            command = build_command(
                "ffmpeg", source, effect, destination, reference, int(params["threads"]),
                encoder, encoder_options, "yuv420p" if use_gpu else None,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return "", bool(use_gpu), "冰峰财神通道参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""


MODE = ModeBinfengCaishen0923()