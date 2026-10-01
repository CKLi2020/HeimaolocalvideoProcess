"""小红书浮光通道。"""

import subprocess
from pathlib import Path

from modes.base_mode import BaseMode
from modes.shipinhao.h264_gpu import select_h264_encoder
from modes.xiaohongshu import mode_xiaohongshu_yanjingshe_worker as worker


class ModeYanjingshe0928(BaseMode):
    id = "xiaohongshu/yanjingshe0928"
    name = "浮光"
    platform = "xiaohongshu"
    needs_aux = False
    gpu_supported = True
    output_suffix = "_yanjingshe0928"
    output_naming = "source"
    ext = "mp4"
    help_text = "小红书处理 · 浮光（单主视频，CPU / NVIDIA / AMD H.264）"

    def has_gpu_command(self):
        return True

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        state = state or {}
        source = Path(main_video or state.get("main_video") or "")
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source

        if use_gpu is None:
            use_gpu = bool(state.get("use_gpu"))
        try:
            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return "", bool(use_gpu), gpu_error
            params = self.build_params(state, str(source))
            destination = Path(str(out_base or params["output"]) + "." + self.ext)
            command = worker.build_command(
                "ffmpeg",
                source,
                destination,
                state.get("metadata_url") or worker.DEFAULT_METADATA_URL,
                encoder,
                encoder_options,
                int(params["threads"]),
            )
        except (OSError, ValueError, KeyError, RuntimeError, worker.WorkerError) as error:
            return "", bool(use_gpu), "浮光参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""


MODE = ModeYanjingshe0928()
