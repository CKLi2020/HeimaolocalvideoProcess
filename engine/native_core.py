"""原生算法核心加载器；源码调试才允许使用 Python 等价实现。"""

from __future__ import annotations

import importlib
import sys

_REQUIRED = (
    "mask_alpha",
    "butterfly_plan",
    "window_matte_chain",
    "concat_filter_segment",
    "playback_rate",
    "filter_segments",
    "color_adjustments_filter",
    "mild_voice_filters",
    "qilin_pipeline_plan",
    "liuying_video_filter",
    "liuying_perspective_filter",
    "liuying_flash_filter",
    "liuying_base_filter",
    "liuying_seed",
    "motianxinglun_pipeline_plan",
    "tianbaixinglun_pipeline_plan",
)

# 第二颗受保护核心 app/_random_frame_swap_core.pyd 的导出清单。它不从这里加载
# （爆闪频道自己 import，见 modes/shipinhao/mode_heimao_luoyue_worker.py），但这
# 里是「发布版必须导出哪些原生符号」的唯一声明处：build_native.ps1 和
# verify_release.py 都读这一个元组，避免源码和已打包的 pyd 版本走散。
RANDOM_SWAP_REQUIRED = (
    "filter_graph",
    "shuffled_order",
    "special_offsets",
)

try:
    from app import _flowcut_core as core
except ImportError:
    core = None

if core is not None and not all(hasattr(core, name) for name in _REQUIRED):
    core = None

if core is None:
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        raise RuntimeError("发布版缺少或无法加载受保护的原生算法核心")
    # 拆开模块名，避免 Nuitka 把仅供源码测试的实现自动收进发布目录。
    core = importlib.import_module("engine." + "dev_core")


def has(name: str) -> bool:
    return hasattr(core, name)
