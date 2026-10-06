"""漫落惊鸿通道选档与命名冒烟检查。"""

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modes.duoduo import tianqiong_heavy, tianqiong_medium
from modes.duoduo.mode_manluo_jinghong import ModeManluoJinghong


with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    ffmpeg = root / "ffmpeg.exe"
    (root / "ffprobe.exe").touch()
    ffmpeg.touch()
    calls = []

    def fake_variant(source, output, rng, seed, crf, keep_temp):
        calls.append((source, output))
        output.touch()
        return {"output": str(output)}

    original_medium = tianqiong_medium.make_variant
    original_heavy = tianqiong_heavy.make_variant
    try:
        tianqiong_medium.make_variant = fake_variant
        tianqiong_heavy.make_variant = fake_variant
        mode = ModeManluoJinghong()
        medium = mode.process(
            {"dedup_mode": "中度"}, "input.mp4", str(root / "input_漫落惊鸿"), str(ffmpeg)
        )
        heavy = mode.process(
            {"dedup_mode": "重度"}, "input.mp4", str(root / "input_漫落惊鸿"), str(ffmpeg)
        )
        assert medium[0].endswith("_中度.mp4")
        assert heavy[0].endswith("_重度.mp4")
        assert len(calls) == 2
    finally:
        tianqiong_medium.make_variant = original_medium
        tianqiong_heavy.make_variant = original_heavy

print("manluo jinghong mode: OK")
