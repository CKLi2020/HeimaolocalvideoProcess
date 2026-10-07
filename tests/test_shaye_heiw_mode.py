"""刹夜黑五通道的参数、命令与核心算法冒烟检查。"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import dev_core
from modes.duoduo import mode_shaye_heiw as channel


channel.core = dev_core
mode = channel.ModeShayeHeiw()
assert mode.output_count({"copies": 3}) == 3
assert mode.output_count({"copies": 999}) == 100

state = {
    "shaye_flash_enabled": True,
    "shaye_flash_value": 5,
    "shaye_audio_enabled": True,
    "shaye_audio_mode": channel.AUDIO_CHINESE,
}
command = channel._base_command(
    Path("ffmpeg"), Path("input.mp4"), Path("output.mp4"), 10.0, 2, state, Path("cover.png"),
)
video_filter = command[command.index("-filter_complex") + 1]
audio_filter = command[command.index("-af") + 1]
assert "fps=120" in video_filter and "boxblur=40:2" in video_filter
assert "overlay=eof_action=pass" in video_filter
assert "asetpts=PTS+random(0.002)-0.001" in audio_filter
assert command[command.index("-ar") + 1] == "88200"
assert command[command.index("-ac") + 1] == "6"

recipe = dev_core.qianchuan_fission_recipe(1_000_000, 120, 576, 1024)
assert 23 <= recipe["frame_interval"] <= 29
assert recipe["target_fps"] == 125
assert (recipe["target_width"], recipe["target_height"]) == (720, 1280)
assert "hqdn3d=4:4:4:4" in dev_core.qianchuan_fission_filter(recipe)
assert dev_core.qianchuan_verify_timestamps([
    {"pts_time": str(index / 120)} for index in range(20)
])
assert not dev_core.qianchuan_verify_timestamps([{"pts_time": "0"}])

with tempfile.TemporaryDirectory() as folder:
    parent = Path(folder)
    with channel._secure_temporary_directory(parent) as secure:
        secret = secure / "plain.mp4"
        secret.write_bytes(b"plaintext")
    assert not secure.exists()

print("shaye heiw mode: OK")
