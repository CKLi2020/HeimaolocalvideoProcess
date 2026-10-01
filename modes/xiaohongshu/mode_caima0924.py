"""小红书晚风通道。"""

import subprocess
import shutil
from pathlib import Path

from modes.xiaohongshu.mode_xiaohongshu_caima_worker import (
    build_command,
    build_stages,
    get_stream,
    probe,
    resolve_tool,
)
from modes.base_mode import BaseMode
from modes.shipinhao.h264_gpu import select_h264_encoder


class ModeCaima0924(BaseMode):
    id = "xiaohongshu/caima0924"
    name = "晚风"
    platform = "xiaohongshu"
    needs_aux = False
    gpu_supported = True
    output_suffix = "_caima0924"
    output_naming = "source"
    ext = "mp4"
    help_text = "小红书处理 · 晚风（单主视频，CPU / NVIDIA / AMD）"

    def has_gpu_command(self):
        return True

    def render_steps(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        source = Path(main_video or (state or {}).get("main_video") or "")
        if not source.is_file():
            return [], False, "输入视频不存在: %s" % source

        if use_gpu is None:
            use_gpu = bool((state or {}).get("use_gpu"))
        try:
            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return [], bool(use_gpu), gpu_error

            root = Path(__file__).resolve().parents[2]
            reference = probe(resolve_tool("ffprobe", root), source)
            get_stream(reference, "video")
            get_stream(reference, "audio")
            params = self.build_params(state or {}, str(source))
            destination_base = str(out_base or params["output"])
            destination = Path(destination_base + "." + self.ext)
            temporary_directory = Path(destination_base + ".caima_work")
            shutil.rmtree(temporary_directory, ignore_errors=True)
            temporary_directory.mkdir(parents=True, exist_ok=True)
            stages = build_stages(
                "ffmpeg", source, destination, temporary_directory, reference,
                encoder, encoder_options, "yuv420p" if use_gpu else None,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return [], bool(use_gpu), "晚风参数生成失败: %s" % error
        return [subprocess.list2cmdline(stage) for stage in stages], bool(use_gpu), ""

    def cleanup_render(self, out_base):
        shutil.rmtree(Path(str(out_base) + ".caima_work"), ignore_errors=True)

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

            root = Path(__file__).resolve().parents[2]
            reference = probe(resolve_tool("ffprobe", root), source)
            get_stream(reference, "video")
            get_stream(reference, "audio")
            params = self.build_params(state or {}, str(source))
            destination = Path(str(out_base or params["output"]) + "." + self.ext)
            command = build_command(
                "ffmpeg", source, destination, reference, encoder, encoder_options,
                "yuv420p" if use_gpu else None,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return "", bool(use_gpu), "晚风参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""


MODE = ModeCaima0924()
