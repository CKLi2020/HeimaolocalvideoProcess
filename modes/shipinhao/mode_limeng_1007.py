"""视频号立梦1007通道。"""

from modes.shipinhao.mode_qixia_mode5 import ModeQixiaMode5


class ModeLimeng1007(ModeQixiaMode5):
    id = "shipinhao/limeng_1007"
    name = "立梦1007"
    sort_priority = -202
    supports_mode5_switches = False
    capture_output = False
    output_suffix = "_limeng_1007"
    help_text = "视频号处理 · 立梦1007（仅主视频，固定倒立，CPU / NVIDIA / AMD，输出文件夹可选）"

    @staticmethod
    def _effect_state(state):
        fixed_state = dict(state or {})
        fixed_state.update({
            "mode5_daoli": True,
            "mode5_lasong": False,
            "mode5_ronghe": False,
        })
        return fixed_state

    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        return super().render(
            self._effect_state(state),
            main_video=main_video,
            aux_video=aux_video,
            use_gpu=use_gpu,
            out_base=out_base,
        )

    def finalize_render(self, out_base, state):
        return super().finalize_render(out_base, self._effect_state(state))


MODE = ModeLimeng1007()
