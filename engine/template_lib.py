"""模板库：模板铺满画布盖在主视频之上，中央窗口挖空，主视频从窗口里透出。

模型来源
--------
参考软件「穿山甲」的 视觉层 → 中央集成 策略，其参数为：

    蒙版区域   [x1, y1, x2, y2]   中央窗口，模板像素坐标
    羽化宽度   60
    填充方式   '全屏'
    分辨率宽/高 720 / 1320
    *蒙版文件夹 '专属模版'
    蒙版顺序   '随机'

「蒙版区域 + 羽化宽度」就是本模块的 `Window`：窗口内透明、窗口外不透明，
过渡带宽度 feather。「填充方式 全屏」意味着**主视频保持整块画布尺寸** ——
窗口只是挖在主视频上的一个洞，主视频并不缩进去，窗口外的模板不透明地
盖住它，被挡住的部分就是挡住了。这些模板是不带 alpha 的整屏明文 mp4，
效果靠主视频这一侧的 alpha 实现，不靠模板透明叠加。

与参考实现的差异（有意为之）
--------------------------
窗口用**画布百分比**而非模板像素坐标表示。模板会被缩放铺满画布，故百分比
与模板自身分辨率无关，滑条上就能直接看出效果，且不必为每种模板分辨率做
坐标换算。5 个字段一一对应：center_x/center_y 是窗口中心，w/h 是窗口尺寸，
feather 是边缘羽化宽度。

清单文件（可选）
----------------
界面上已经没有「清单文件名」这一行了：用户不需要它。要逐张模板微调窗口几何时，
才在模板目录里手放一个 `模板/模板.json`（文件名由 `config.tpl_manifest` 指定）。
支持「全局默认 + 每模板覆盖」：

    {
      "version": 1,
      "defaults":  { "window_center_x": 50, "window_center_y": 44,
                     "window_w": 80, "window_h": 55, "window_feather": 60 },
      "templates": [
        { "file": "llzmtsc (1).mp4", "window_center_y": 42 },
        { "file": "llzmtsc (2).mp4", "window_w": 90, "window_h": 60 }
      ]
    }

取值优先级：每模板条目 > defaults > config 全局字段。
清单缺失或损坏 → 退回「扫描模板目录 + config 全局字段」，不报错。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from engine.native_core import core as _native_core

# 窗口字段：清单 defaults 与每模板覆盖都只认这 5 个
WINDOW_FIELDS = ("window_center_x", "window_center_y", "window_w", "window_h",
                 "window_feather")

@dataclass(frozen=True)
class Window:
    """主视频窗口几何，全部是画布百分比（feather 是以 1080 短边为基准的像素数）。"""

    center_x: int
    center_y: int
    width: int
    height: int
    feather: int


@dataclass(frozen=True)
class WindowMatte:
    """几何蒙版：从 gray 帧到羽化蒙版的完整滤镜链（不带标签）。"""

    chain: str


def window_matte(window: Window, canvas: tuple[int, int]) -> WindowMatte:
    """返回把主视频收进「模板窗口」的几何蒙版链。

    语义：窗口内不透明、窗口外全透明、边缘按 feather 羽化。模板铺满画布
    盖在主视频上（`[bg][main]overlay`），靠这条 alpha 让主视频只从窗口里
    透出来：窗口外的模板不透明地挡住主视频，过渡带负责把两边融合在一起。
    窗口给到比画布还大（例如 120%）就等于不挖洞，模板全被主视频盖住。

    为什么不用 geq
    --------------
    全屏 geq 是逐像素表达式求值，实测把整片渲染拖慢到 **4.4 倍**（60 秒
    1080x2338：1分20秒 → 5分33秒），而这里要的只是一个羽化矩形。drawbox
    画出来、boxblur 抹一圈就够了，代价约 1.4 倍。

    drawbox 后面为什么还跟一次 lutyuv
    --------------------------------
    ffmpeg 画颜色时对 yuv/gray 帧做**有限范围**映射，白落到 gray 上是 235
    而不是 255（已实测）。235 直接当 alpha 用，窗口内就只有 92% 不透明，
    模板会整片透上来一层，实拍出来是「主视频发灰」。所以画完先二值化拉回
    0/255，再做羽化 —— 这一步是定值查表，不是逐像素算表达式，几乎不花钱。

    x/y 为什么要写成 iw/2
    --------------------
    蒙版是贴在**主视频帧**上的，而窗口是按画布坐标给的。主视频居中叠在画布上，
    帧内坐标 = 画布坐标 + (帧尺寸 - 画布尺寸)/2。主视频「适配画布」时比画布
    小（带黑边），帧尺寸只有 ffmpeg 知道，所以常数项只保留 (画布坐标 - 画布/2)，
    另一半交给 drawbox 表达式里的 iw/2、ih/2 —— 这样不必预先探测主视频分辨率，
    对齐也不会因为黑边而整体错位。
    """
    cw, ch = canvas
    return WindowMatte(chain=_native_core.window_matte_chain(
        cw, ch,
        window.center_x, window.center_y,
        window.width, window.height,
        window.feather,
    ))


@dataclass(frozen=True)
class TemplateSpec:
    """一个模板文件 + 它对窗口全局值的覆盖。"""

    path: Path
    overrides: dict


class TemplateLibrary:
    """模板集合 + 解析后的窗口几何。"""

    def __init__(self, specs: list[TemplateSpec], defaults: dict):
        self.specs = specs
        self.defaults = defaults

    def __bool__(self) -> bool:
        return bool(self.specs)

    def pick(self, order: str = "随机",
             fixed_name: str = "") -> Optional[TemplateSpec]:
        """取本次要用的模板。空库返回 None。

        order == "固定" 且 fixed_name 在库里 → 每次都用这一张（整批同一个模板）；
        否则随机。固定项找不到时**退回随机而不是报错**：文件被删掉或改名了不该
        让整批出不了片，调用方可用 has() 判断是不是真的命中了，据此提示用户。
        """
        if not self.specs:
            return None
        if order == "固定" and fixed_name:
            for spec in self.specs:
                if spec.path.name == fixed_name:
                    return spec
        import random

        return random.choice(self.specs)

    def has(self, name: str) -> bool:
        """库里有叫 name 的模板吗（固定模板没命中时用来提示）。"""
        return any(spec.path.name == name for spec in self.specs)

    def resolve(self, spec: TemplateSpec, config) -> Window:
        """合并 每模板覆盖 > 清单 defaults > config 全局，返回窗口几何。

        窗口尺寸夹在 1%~100%，中心允许负值/超界 —— 窗口超出画布是合法的，
        那等于「这条边不挖洞」，整条边都留给模板。feather 上限 400，0 表示硬边。
        """
        values = {name: getattr(config, f"tpl_{name}") for name in WINDOW_FIELDS}
        for name in WINDOW_FIELDS:
            if name in self.defaults:
                values[name] = self.defaults[name]
        for name in WINDOW_FIELDS:
            if name in spec.overrides:
                values[name] = spec.overrides[name]

        def _clamp(raw, low, high, fallback):
            try:
                return max(low, min(high, int(raw)))
            except (TypeError, ValueError):
                return fallback

        return Window(
            center_x=_clamp(values["window_center_x"], -100, 200, 50),
            center_y=_clamp(values["window_center_y"], -100, 200, 50),
            width=_clamp(values["window_w"], 1, 100, 80),
            height=_clamp(values["window_h"], 1, 100, 55),
            feather=_clamp(values["window_feather"], 0, 400, 60),
        )


def _read_manifest(path: Path) -> tuple[dict, list]:
    """读清单，返回 (defaults, entries)。任何异常都退回空值。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, []
    if not isinstance(data, dict):
        return {}, []
    defaults = data.get("defaults")
    entries = data.get("templates")
    defaults = defaults if isinstance(defaults, dict) else {}
    entries = entries if isinstance(entries, list) else []
    return defaults, entries


def _video_files(folder: Path) -> list[Path]:
    from engine.ffmpeg_builder import VIDEO_EXTS, list_media

    return list_media(str(folder), VIDEO_EXTS)


def load_library(folder: Path, manifest_name: str = "模板.json") -> TemplateLibrary:
    """扫描模板目录，并叠加可选清单。

    Args:
        folder: 模板库目录
        manifest_name: 清单文件名（相对 folder）

    Returns:
        TemplateLibrary；目录不存在或没有视频时 specs 为空（bool 为 False）。
    """
    folder = Path(folder)  # 调用方给的可能是 config 里的字符串
    if not folder.is_dir():
        return TemplateLibrary([], {})

    files = _video_files(folder)
    if not files:
        return TemplateLibrary([], {})

    by_name = {f.name: f for f in files}
    defaults, entries = _read_manifest(folder / manifest_name) if manifest_name else ({}, [])

    # 清单里列出的文件优先并保持清单顺序；未列出的文件追加在后面。
    # 清单指向不存在的文件时跳过（不报错）。
    specs: list[TemplateSpec] = []
    listed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("file")
        if not isinstance(name, str) or name in listed:
            continue
        path = by_name.get(name)
        if path is None:
            continue
        listed.add(name)
        overrides = {k: v for k, v in entry.items() if k in WINDOW_FIELDS}
        specs.append(TemplateSpec(path=path, overrides=overrides))

    for name, path in by_name.items():
        if name not in listed:
            specs.append(TemplateSpec(path=path, overrides={}))

    return TemplateLibrary(specs, defaults)
