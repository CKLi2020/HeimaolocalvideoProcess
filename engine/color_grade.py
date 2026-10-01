"""调色滤镜引擎：预设滤镜 + 手动微调。

预设滤镜通过 ffmpeg eq/colorbalance/curves/hue 组合实现：
- 晴川: 提亮青绿调，日系清新
- 暖阳: 暖黄调，增加色温
- 复古: 降低饱和度 + 暖色偏移
- 黑白: 完全去饱和
- 冷色: 蓝调偏移
- 胶片: 微对比 + 微褪色
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from engine.native_core import core as _native_core


class ColorPreset:
    """调色预设：一组 ffmpeg 滤镜参数。"""

    def __init__(
        self,
        name: str,
        brightness: float = 0.0,
        contrast: float = 1.0,
        saturation: float = 1.0,
        temperature: float = 0.0,
        hue_shift: float = 0.0,
        gamma_r: float = 1.0,
        gamma_g: float = 1.0,
        gamma_b: float = 1.0,
        vignette: float = 0.0,
    ):
        self.name = name
        self.brightness = brightness
        self.contrast = contrast
        self.saturation = saturation
        self.temperature = temperature
        self.hue_shift = hue_shift
        self.gamma_r = gamma_r
        self.gamma_g = gamma_g
        self.gamma_b = gamma_b
        self.vignette = vignette

    def apply_to_ffmpeg_filter(self, base_tag: str) -> Tuple[str, str]:
        """生成 ffmpeg filter_complex 片段。

        Returns:
            (filter_string, output_tag)
        """
        parts = []

        # gamma / colorbalance
        if (abs(self.gamma_r - 1.0) > 0.01
                or abs(self.gamma_g - 1.0) > 0.01
                or abs(self.gamma_b - 1.0) > 0.01):
            parts.append(
                f"colorbalance=rh={self.gamma_r - 1.0:.2f}:"
                f"gh={self.gamma_g - 1.0:.2f}:"
                f"bh={self.gamma_b - 1.0:.2f}"
            )

        # hue
        if abs(self.hue_shift) > 0.01:
            parts.append(f"hue=h={self.hue_shift:.1f}")

        # eq (亮度/对比度/饱和度/色温)
        eq_parts = []
        if abs(self.brightness) > 0.01:
            eq_parts.append(f"brightness={self.brightness:.2f}")
        if abs(self.contrast - 1.0) > 0.01:
            eq_parts.append(f"contrast={self.contrast:.2f}")
        if abs(self.saturation - 1.0) > 0.01:
            eq_parts.append(f"saturation={self.saturation:.2f}")
        if abs(self.temperature) > 1:
            eq_parts.append(f"temperature={int(3000 + self.temperature * 2000)}")
        if eq_parts:
            parts.append(f"eq={':'.join(eq_parts)}")

        # vignette - handled separately in ffmpeg_builder

        if not parts:
            return "", base_tag

        tag = f"{base_tag}_color"
        filter_str = f"[{base_tag}]{','.join(parts)}[{tag}]"
        return filter_str, tag


# ═════════════════════════════════════════════
# 预设滤镜库
# ═════════════════════════════════════════════

PRESETS: Dict[str, ColorPreset] = {
    "晴川": ColorPreset(
        name="晴川",
        brightness=0.05,
        contrast=1.05,
        saturation=1.1,
        temperature=7500,  # 偏暖
        gamma_r=1.02,
        gamma_g=1.05,
        gamma_b=1.08,
    ),
    "暖阳": ColorPreset(
        name="暖阳",
        brightness=0.08,
        contrast=1.02,
        saturation=1.15,
        temperature=9000,  # 更暖
        gamma_r=1.10,
        gamma_g=1.05,
        gamma_b=0.95,
    ),
    "复古": ColorPreset(
        name="复古",
        brightness=-0.03,
        contrast=1.10,
        saturation=0.65,
        temperature=8000,  # 暖色调
        gamma_r=1.12,
        gamma_g=1.02,
        gamma_b=0.90,
        vignette=0.15,
    ),
    "黑白": ColorPreset(
        name="黑白",
        brightness=0.0,
        contrast=1.15,
        saturation=0.0,
        temperature=6500,  # 标准色温
    ),
    "冷色": ColorPreset(
        name="冷色",
        brightness=-0.02,
        contrast=1.05,
        saturation=0.95,
        temperature=4000,  # 偏冷
        gamma_r=0.95,
        gamma_g=1.0,
        gamma_b=1.10,
    ),
    "胶片": ColorPreset(
        name="胶片",
        brightness=0.02,
        contrast=1.08,
        saturation=0.85,
        temperature=7000,
        gamma_r=1.04,
        gamma_g=1.02,
        gamma_b=1.06,
        vignette=0.10,
    ),
    "鲜明": ColorPreset(
        name="鲜明",
        brightness=0.05,
        contrast=1.12,
        saturation=1.20,
        temperature=6500,
    ),
    "淡雅": ColorPreset(
        name="淡雅",
        brightness=0.10,
        contrast=0.95,
        saturation=0.85,
        temperature=5500,
        gamma_r=1.02,
        gamma_g=1.04,
        gamma_b=1.03,
    ),
    "无": ColorPreset(
        name="无",
    ),
}

RANDOM_PRESETS = tuple(name for name in PRESETS if name != "无")


def get_preset(name: str) -> Optional[ColorPreset]:
    """获取指定名称的滤镜预设。"""
    return PRESETS.get(name)


def list_presets() -> List[str]:
    """列出所有可用预设名称。"""
    return list(PRESETS.keys())


def resolve_preset_name(name: str) -> str:
    """「随机」在每个输出任务开始时固定成一个真实预设。"""
    return _native_core.filter_segments(1)[0] if name == "随机" else name


def apply_color_adjustments(
    base_tag: str,
    brightness: int = 0,
    contrast: int = 0,
    saturation: int = 0,
    temperature: int = 0,
    vignette: int = 0,
    filter_name: str = "",
    filter_strength: int = 100,
) -> Tuple[str, str]:
    """综合应用预设滤镜 + 手动调色参数。

    Args:
        base_tag: 输入流标签
        brightness: -100 到 100
        contrast: -100 到 100
        saturation: -100 到 100
        temperature: -100 到 100
        vignette: 0 到 100
        filter_name: 预设滤镜名称，空字符串表示不用
        filter_strength: 滤镜强度 (0-100)

    Returns:
        (filter_complex 片段字符串, 输出标签)
    """
    return _native_core.color_adjustments_filter(
        base_tag, brightness, contrast, saturation, temperature,
        filter_name, filter_strength,
    )
