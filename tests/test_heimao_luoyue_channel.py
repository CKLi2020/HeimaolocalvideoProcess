import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modes import load_modes
from modes.shipinhao.mode_heimao_luoyue import MODE
from modes.shipinhao import mode_heimao_luoyue_worker as worker


groups = load_modes()
assert MODE in groups["视频号处理"]
# 爆闪必须是这个分组里id 唯一的一条，但不再是第一条：08e49b3 把星火的流萤/栖霞
# 并入视频号分组后，下拉框排序变了。这里只断言注册本身，不断言展示顺序。
assert sum(1 for mode in groups["视频号处理"] if mode.id == MODE.id) == 1
assert MODE.name == "爆闪"
assert not MODE.needs_aux and MODE.has_gpu_command() and MODE.supports_copies
assert MODE.output_count({"copies": 999}) == 100

original_run_many = worker.run_many
captured = []
try:
    def fake_run_many(_source, outputs, _ffmpeg, **_kwargs):
        captured.extend(outputs)
        return len(outputs)

    worker.run_many = fake_run_many
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source.mp4"
        source.touch()
        outputs = MODE.process(
            {"copies": 3, "gpu_profile": {}}, source,
            str(Path(directory) / "source_heimao_luoyue"), "ffmpeg",
        )
        names = [path.name for path in outputs]
        assert outputs == captured and len(set(names)) == 3
        assert all(re.fullmatch(r"source爆闪[a-z0-9]{4}\.mp4", name) for name in names)
finally:
    worker.run_many = original_run_many

worker.self_test()
print("heimao luoyue channel: OK")
