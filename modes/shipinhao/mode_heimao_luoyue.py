"""视频号·爆闪随机帧交错通道。"""

from pathlib import Path

from engine.output_naming import channel_output_stem
from modes.base_mode import BaseMode
from modes.shipinhao import mode_heimao_luoyue_worker as worker


class ModeHeimaoLuoyue(BaseMode):
    id = "shipinhao/heimao_luoyue"
    name = "爆闪"
    sort_priority = -100
    platform = "shipinhao"
    needs_aux = False
    gpu_supported = True
    supports_copies = True
    output_suffix = "_heimao_luoyue"
    output_naming = "source"
    ext = "mp4"
    help_text = "视频号处理 · 爆闪（随机帧重排交错，NVIDIA / CPU）"

    def has_gpu_command(self):
        return True

    @staticmethod
    def output_count(state):
        return max(1, min(100, int(state.get("copies", 1))))

    def _next_output(self, source, output_dir, reserved):
        while True:
            candidate = output_dir / f"{channel_output_stem(source, self.name)}.mp4"
            if candidate not in reserved and not candidate.exists():
                return candidate

    def process(self, state, main_video, output_base, ffmpeg, use_gpu=False,
                on_log=None, on_progress=None, should_stop=None):
        source = Path(main_video)
        if not source.is_file():
            raise ValueError(f"输入视频不存在: {source}")
        vendor = (state.get("gpu_profile") or {}).get("vendor")
        encoder = "h264_nvenc" if use_gpu and vendor == "nvidia" else "libx264"
        if on_log:
            on_log("  爆闪：" + ("NVIDIA GPU 处理" if encoder == "h264_nvenc" else "CPU 处理"))

        last_stage = [None]

        def report(stage, current, total, _output_index):
            if on_log and stage != last_stage[0]:
                on_log("  " + stage)
                last_stage[0] = stage
            if on_progress and total:
                ratio = min(1.0, current / total)
                on_progress((ratio * 45.0) if stage == "缓存视频帧" else (45.0 + ratio * 55.0))

        output_dir = Path(output_base).parent
        outputs = []
        for _ in range(self.output_count(state)):
            outputs.append(self._next_output(source, output_dir, set(outputs)))
        completed = worker.run_many(
            source,
            outputs,
            ffmpeg,
            seed=None,
            encoder=encoder,
            should_stop=should_stop,
            on_progress=report,
        )
        if completed != len(outputs) and not (should_stop and should_stop()):
            raise RuntimeError("爆闪通道未生成产物")
        return outputs[:completed]


MODE = ModeHeimaoLuoyue()
