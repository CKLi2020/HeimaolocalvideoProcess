"""视频号流萤通道。"""

import os
import secrets
import subprocess
from pathlib import Path

from engine.native_core import core as _native_core
from modes.base_mode import BaseMode
from modes.shipinhao import mode_shipinghao_chuanshanjia_v15_worker as worker
from modes.shipinhao.h264_gpu import select_h264_encoder


class ModeLiuyingV15(BaseMode):
    id = "shipinhao/liuying_v15"
    name = "流萤1003"
    sort_priority = -200
    platform = "shipinhao"
    needs_aux = False
    gpu_supported = True
    supports_copies = True
    output_suffix = "_liuying_v15"
    output_naming = "source"
    ext = "mp4"
    help_text = (
        "视频号处理 · 流萤（固定随机闪帧；仅需主视频，"
        "CPU / NVIDIA / AMD；裂变每份独立处理，额外随机画面增强关闭）"
    )

    def __init__(self):
        self._references = {}

    def has_gpu_command(self):
        return True

    @staticmethod
    def output_count(state):
        return max(1, min(100, int(state.get("copies", 1))))

    @staticmethod
    def prepare_batch_state(state):
        batch_state = dict(state)
        if batch_state.get("random_seed") is None:
            batch_state["random_seed"] = secrets.randbits(48)
        else:
            batch_state["random_seed"] = int(batch_state["random_seed"])
        return batch_state

    @staticmethod
    def state_for_copy(state, task_index):
        copy_state = dict(state)
        copy_state["random_seed"] = _native_core.liuying_seed(
            state["random_seed"], task_index
        )
        return copy_state

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        state = state or {}
        source = Path(main_video or state.get("main_video") or "")
        reference = source
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source

        if use_gpu is None:
            use_gpu = bool(state.get("use_gpu"))
        try:
            root = Path(__file__).resolve().parents[2]
            ffprobe = worker.resolve_tool("ffprobe", root)
            source_probe = worker.run_probe(ffprobe, source)
            if not any(s.get("codec_type") == "video" for s in source_probe.get("streams", [])):
                raise ValueError("主视频没有视频流")
            if not any(s.get("codec_type") == "audio" for s in source_probe.get("streams", [])):
                raise ValueError("主视频没有音频流")

            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return "", bool(use_gpu), gpu_error
            params = self.build_params(state, str(source), str(source))
            base = str(out_base or params["output"])
            encoded = Path(base + ".encoding.mp4")
            command = worker.build_command(
                "ffmpeg",
                source,
                encoded,
                int(params["threads"]),
                encoder,
                encoder_options,
                False,
                (
                    int(state["random_seed"])
                    if state.get("random_seed") is not None
                    else None
                ),
            )
            self._references[base] = reference
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return "", bool(use_gpu), "流萤参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""

    def finalize_render(self, out_base, state):
        base = str(out_base)
        encoded = Path(base + ".encoding.mp4")
        output = Path(base + ".mp4")
        reference = self._references.get(base)
        if reference is None:
            raise RuntimeError("未找到流萤主视频校验参考")

        worker.retime_video_track(encoded, worker.DECLARED_VIDEO_FPS)
        os.replace(encoded, output)
        root = Path(__file__).resolve().parents[2]
        ffprobe = worker.resolve_tool("ffprobe", root)
        expected = worker.run_probe(ffprobe, reference)
        actual = worker.run_probe(ffprobe, output)
        expected_layout = [stream.get("codec_type") for stream in expected.get("streams", [])]
        actual_layout = [stream.get("codec_type") for stream in actual.get("streams", [])]
        if sorted(expected_layout) != sorted(actual_layout):
            raise RuntimeError(
                "辅助校验视频与成片的流类型/数量不匹配: "
                f"expected {expected_layout!r}, got {actual_layout!r}"
            )

    def cleanup_render(self, out_base):
        base = str(out_base)
        Path(base + ".encoding.mp4").unlink(missing_ok=True)
        self._references.pop(base, None)


MODE = ModeLiuyingV15()
