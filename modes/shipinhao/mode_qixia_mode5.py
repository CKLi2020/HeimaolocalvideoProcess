"""视频号栖霞通道。"""

import subprocess
from pathlib import Path

from modes.base_mode import BaseMode
from modes.shipinhao import mode_shipinghao_mode5_combined_worker as worker
from modes.shipinhao.h264_gpu import select_h264_encoder


class ModeQixiaMode5(BaseMode):
    id = "shipinhao/qixia_mode5"
    name = "栖霞"
    sort_priority = -150
    platform = "shipinhao"
    needs_aux = True
    gpu_supported = True
    supports_copies = True
    supports_mode5_switches = True
    output_suffix = "_qixia_mode5"
    output_naming = "source"
    ext = "mp4"
    help_text = "视频号处理 · 栖霞（主视频 + 辅助视频，拉松 / 融合 / 倒立，CPU / NVIDIA / AMD）"

    def has_gpu_command(self):
        return True

    @staticmethod
    def output_count(state):
        return max(1, min(100, int(state.get("copies", 1))))

    @staticmethod
    def _paths(out_base):
        output = Path(str(out_base) + ".mp4")
        encoded = output.with_name(output.name + ".encoding.mp4")
        return encoded, output

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        state = state or {}
        source = Path(main_video or state.get("main_video") or "")
        auxiliary = Path(aux_video or state.get("aux_video") or "")
        if not source.is_file():
            return "", False, "输入视频不存在: %s" % source
        if not auxiliary.is_file():
            return "", False, "辅视频不存在: %s" % auxiliary

        daoli = bool(state.get("mode5_daoli"))
        lasong = bool(state.get("mode5_lasong"))
        ronghe = bool(state.get("mode5_ronghe"))

        try:
            if use_gpu is None:
                use_gpu = bool(state.get("use_gpu"))
            encoder, encoder_options, gpu_error = select_h264_encoder(state, use_gpu)
            if gpu_error:
                return "", bool(use_gpu), gpu_error
            params = self.build_params(state, str(source), str(auxiliary))
            encoded, _output = self._paths(out_base or params["output"])
            command = worker.build_ffmpeg_command(
                Path("ffmpeg"),
                source,
                encoded,
                auxiliary_path=auxiliary,
                video_encoder=encoder,
                encoder_options=encoder_options,
                threads=int(params["threads"]),
                daoli=daoli,
                lasong=lasong,
                ronghe=ronghe,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return "", bool(use_gpu), "栖霞参数生成失败: %s" % error
        return subprocess.list2cmdline(command), bool(use_gpu), ""

    def finalize_render(self, out_base, state):
        encoded, output = self._paths(out_base)
        worker.rewrite_timing(encoded, output, flip=bool((state or {}).get("mode5_daoli")))

    def cleanup_render(self, out_base):
        encoded, _output = self._paths(out_base)
        encoded.unlink(missing_ok=True)


MODE = ModeQixiaMode5()
