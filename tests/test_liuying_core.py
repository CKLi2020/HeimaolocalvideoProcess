"""流萤1003 的关键滤镜必须由 native_core 提供。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.native_core import core


def test_liuying_core_filters():
    standard = core.liuying_video_filter(1003)
    enhanced = core.liuying_video_filter(1003, True)
    branch = core.liuying_perspective_filter(1003)
    flash = core.liuying_flash_filter(1003)

    assert standard.startswith("fps=60,scale=576:1248")
    assert standard.count("perspective=") == 1
    assert enhanced.count("perspective=") == 2
    assert "st(0,1003+(ceil(in/12))*104729)" in standard
    assert branch.startswith("perspective=")
    assert "st(0,1003+(in)*104729)" in branch
    assert "ceil(in/12)" in flash
    assert core.liuying_base_filter().startswith("fps=60,scale=576:1248")
    assert core.liuying_seed(1003, 2) == 210461


if __name__ == "__main__":
    test_liuying_core_filters()
    print("liuying core test: OK")
