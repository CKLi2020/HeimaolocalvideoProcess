"""抖音听雪通道09284。"""

import subprocess
from pathlib import Path

import mode_douyin_feimao_worker as worker
from modes.base_mode import BaseMode
from modes.douyin.hevc_gpu import select_hevc_encoder


class ModeFeimao09284(BaseMode):
    id = "douyin/feimao09284"
    name = "听雪通道09284"
    platform = "douyin"
    needs_aux = False
    gpu_supported = True
    output_suffix = "_feimao09284"
    output_naming = "source"
    ext = "mp4"
    help_text = "抖音处理 · 听雪通道09284（单主视频，CPU / NVIDIA / AMD HEVC）"

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
            encoder, encoder_options, gpu_error = select_hevc_encoder(state, use_gpu)
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
                "hvc1",
            )
        except (OSError, ValueError, KeyError, RuntimeError, worker.WorkerError) as error:
            return "", bool(use_gpu), "听雪通道参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""


MODE = ModeFeimao09284()