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
    "qilin_sps_compat_byte",
    "liuying_video_filter",
    "liuying_perspective_filter",
    "liuying_flash_filter",
    "liuying_base_filter",
    "liuying_seed",
    "motianxinglun_pipeline_plan",
    "tianbaixinglun_pipeline_plan",
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
