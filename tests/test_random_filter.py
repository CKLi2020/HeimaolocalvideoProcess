"""随机滤镜只会解析为真实预设。可直接 `python tests/test_random_filter.py`。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.color_grade import RANDOM_PRESETS, resolve_preset_name
from config import AppConfig


assert "无" not in RANDOM_PRESETS
assert "随机" not in RANDOM_PRESETS
assert resolve_preset_name("无") == "无"
assert all(resolve_preset_name("随机") in RANDOM_PRESETS for _ in range(100))
assert AppConfig().filter_segment_count == 1
assert AppConfig().filter_name == ""
assert AppConfig().aux_overlay_count == 3
assert AppConfig().kaimu_enabled
assert not AppConfig().audio_voice_mild
assert (AppConfig().playback_speed_min, AppConfig().playback_speed_max) == (1.0, 1.0)

print("random filter: OK")
