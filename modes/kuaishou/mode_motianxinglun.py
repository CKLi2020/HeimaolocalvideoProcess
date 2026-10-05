"""快手星河摩轮通道。"""

import subprocess
from pathlib import Path

from modes.base_mode import BaseMode
from modes.kuaishou.h264_gpu import select_h264_encoder
from modes.kuaishou import mode_kuaishou_motianxinglun_worker as worker


class ModeMotianxinglun(BaseMode):
    id = "kuaishou/motianxinglun"
    name = "星河摩轮1005"
    sort_priority = -300
    platform = "kuaishou"
    needs_aux = False
    gpu_supported = True
    output_suffix = "_motianxinglun"
    output_naming = "source"
    ext = "mp4"
    expected_video_tracks = 2
    help_text = "快手处理 · 星河摩轮1005（主视频输入，CPU / NVIDIA / AMD）"

    def __init__(self):
        self._work_dirs = {}

    def has_gpu_command(self):
        return True

    def render_steps(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        state = state or {}
        source = Path(main_video or state.get("main_video") or "")
        if not source.is_file():
            return [], False, "输入视频不存在: %s" % source

        if use_gpu is None:
            use_gpu = bool(state.get("use_gpu"))
        try:
            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return [], bool(use_gpu), gpu_error
            ffmpeg = worker.resolve_tool("ffmpeg.exe")
            ffprobe = worker.resolve_tool("ffprobe.exe")
            source_probe = worker.probe(ffprobe, source)
            if not any(
                item.get("codec_type") == "video"
                for item in source_probe.get("streams", [])
            ):
                raise ValueError("主视频没有视频流")
            duration = float(source_probe.get("format", {}).get("duration"))

            params = self.build_params(state, str(source), None)
            base = str(out_base or params["output"])
            output = Path(base + "." + self.ext)
            work = Path(base + ".motianxinglun_work")
            self._work_dirs[base] = work
            commands = worker.build_commands(
                str(ffmpeg), source, output, work, duration,
                int(params["threads"]), encoder, encoder_options,
            )
        except (OSError, TypeError, ValueError, KeyError, RuntimeError,
                worker.ProcessingError) as error:
            return [], bool(use_gpu), "星河摩轮参数生成失败: %s" % error
        return [subprocess.list2cmdline(command) for command in commands], bool(use_gpu), ""

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        gpu_requested = use_gpu if use_gpu is not None else (state or {}).get("use_gpu")
        return "", bool(gpu_requested), "星河摩轮为多阶段通道，请由本地处理服务调用 render_steps"

    def cleanup_render(self, out_base):
        base = str(out_base)
        work = self._work_dirs.pop(base, None)
        if work is not None and work.exists():
            for item in work.iterdir():
                item.unlink()
            work.rmdir()


MODE = ModeMotianxinglun()
