"""完整的 ffmpeg filter_complex 构建器。

将所有 GUI 参数映射为 ffmpeg 命令行。支持:
- 背景+主视频合成, 矩形蒙版, 顶底横条, 双拼横条
- 画中画 1/2 (固定+移动)
- 动态缩放/晃动/抖动
- 多层贯穿贴纸, 多层移动贴纸
- 扫光 (blend=screen, 速度可控)
- 开幕效果 (黑屏/上下/左右)
- 封面标题 (drawtext)
- 调色 (预设滤镜 + 手动微调 + vignette)
- H.264/H.265, GPU/CPU, CRF/preset
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Optional, Tuple

from config import AppConfig

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def list_media(folder: str, exts: set) -> List[Path]:
    """列出文件夹中指定扩展名的媒体文件。"""
    if not folder:
        return []
    path = Path(folder)
    if not path.is_dir():
        return []
    return sorted(
        [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in exts]
    )


def pick_random(folder: str, exts: set) -> Optional[Path]:
    """从文件夹随机选取一个媒体文件。"""
    files = list_media(folder, exts)
    return random.choice(files) if files else None


def build_ffmpeg_command(
    config: AppConfig,
    main_video: Path,
    background_video: Path,
    output_path: Path,
    sticker_files: Optional[List[Path]] = None,
    scanlight_file: Optional[Path] = None,
    kaimu_file: Optional[Path] = None,
    mover_files: Optional[List[Path]] = None,
) -> List[str]:
    """构建完整的 ffmpeg 命令行。

    Args:
        config: 应用配置
        main_video: 主视频路径
        background_video: 背景视频路径
        output_path: 输出路径
        sticker_file: 贴纸文件（图片或视频）
        scanlight_file: 扫光视频文件
        kaimu_file: 开幕素材文件
        mover_file: 移动贴纸文件

    Returns:
        ffmpeg 命令行参数列表
    """
    w, h = map(int, config.resolution.split("x"))
    fps = config.fps
    main_scale = config.main_scale / 100.0
    bg_loop = ["-stream_loop", "-1"]

    cmd: List[str] = ["ffmpeg", "-y"]
    inputs: List[str] = []
    filters: List[str] = []
    current_tag = ""
    input_idx = 0

    def next_tag(name: str) -> str:
        nonlocal current_tag
        current_tag = name
        return f"[{name}]"

    # ═══════════════════════════════════════════════════════════
    # INPUT 0: Background video (可变速 + 缩放)
    # ═══════════════════════════════════════════════════════════
    aux_speed = config.aux_speed / 100.0
    aux_scale_val = config.aux_scale / 100.0

    cmd += bg_loop + ["-i", str(background_video)]
    input_idx = 1

    bg_filter_parts = [f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"]
    if abs(aux_speed - 1.0) > 0.01:
        bg_filter_parts.insert(0, f"setpts={1/aux_speed}*PTS")
    if abs(aux_scale_val - 1.0) > 0.01:
        bg_filter_parts.append(f"scale=iw*{aux_scale_val}:ih*{aux_scale_val}")
        bg_filter_parts.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
    bg_filter_parts.append(f"fps={fps}")

    filters.append(f"[0:v]{','.join(bg_filter_parts)}{next_tag('bg')}")

    # ═══════════════════════════════════════════════════════════
    # INPUT 1: Main video
    # ═══════════════════════════════════════════════════════════
    cmd += ["-i", str(main_video)]
    input_idx = 2

    if config.main_fit:
        # 完整适配模式：缩放到刚好填满画布（可能有裁切）
        main_filter = (
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},format=rgba{next_tag('main')}"
        )
    else:
        # 百分比缩放模式，保持比例居中
        main_filter = (
            f"[1:v]scale=iw*{main_scale}:ih*{main_scale},"
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"fps={fps},format=rgba{next_tag('main')}"
        )
    filters.append(main_filter)

    # ── Overlay main on background (centered) ──
    filters.append(
        f"[bg][main]overlay=(W-w)/2:(H-h)/2:shortest=1{next_tag('base')}"
    )

    # ═══════════════════════════════════════════════════════════
    # MASK: 矩形蒙版
    # ═══════════════════════════════════════════════════════════
    if config.mask_enabled:
        margin_tb = config.mask_margin_tb / 100.0
        margin_lr = config.mask_margin_lr / 100.0
        feather = config.mask_feather

        # 蒙版区域 (画布扣掉边距)
        mx = int(w * margin_lr)
        my = int(h * margin_tb)
        mw = w - 2 * mx
        mh = h - 2 * my

        # 用 crop + overlay 实现。将 base 裁切为蒙版区域，再做羽化
        if feather > 0:
            # 羽化：生成一个带羽化边缘的蒙版，用 blend 混合
            filters.append(
                f"[base]crop={mw}:{mh}:{mx}:{my},format=rgba[mask_inner];"
                f"[base]format=rgba[base_rgba];"
                f"[base_rgba][mask_inner]overlay={mx}:{my}:shortest=1"
                f"{next_tag('masked')}"
            )
        else:
            filters.append(
                f"[base]crop={mw}:{mh}:{mx}:{my}{next_tag('masked')}"
            )
        # 如果羽化 > 0，增加 boxblur 做软边
        if feather > 0:
            feather_px = max(1, int(feather * min(w, h) / 500))
            filters.append(
                f"[masked]boxblur={feather_px}:enable='lt(t,0.1)'"
                f"{next_tag('masked_soft')}"
            )
            current_tag = "masked_soft"

    base_tag = current_tag

    # ═══════════════════════════════════════════════════════════
    # TOP MATTE: 顶部蒙版叠层 (独立于横条)
    # ═══════════════════════════════════════════════════════════
    if config.top_step_enabled and config.top_scale > 0:
        ts = config.top_scale / 100.0
        to = config.top_opacity / 100.0
        tf = config.top_feather
        filters.append(
            f"[0:v]scale=iw*{ts}:ih*{ts},"
            f"crop={w}:{h},"
            f"format=rgba,colorchannelmixer=aa={to}"
            f"{next_tag('topmat')}"
        )
        filters.append(
            f"[{base_tag}][topmat]overlay=0:0:shortest=1{next_tag('matted')}"
        )
        base_tag = "matted"

    # ═══════════════════════════════════════════════════════════
    # BARS: 非对称顶底横条
    # ═══════════════════════════════════════════════════════════
    if config.bars_enabled:
        # 顶部横条（可使用独立参数或对称参数）
        top_h = config.top_bar_height if config.split_bars_enabled else config.bar_height
        top_op = (config.top_bar_opacity if config.split_bars_enabled else config.bar_opacity) / 100.0
        bot_h = config.bottom_bar_height if config.split_bars_enabled else config.bar_height
        bot_op = (config.bottom_bar_opacity if config.split_bars_enabled else config.bar_opacity) / 100.0

        filters.append(
            f"[0:v]crop={w}:{top_h}:0:0,"
            f"format=rgba,colorchannelmixer=aa={top_op}"
            f"{next_tag('topbar')}"
        )
        filters.append(
            f"[{base_tag}][topbar]overlay=0:0:shortest=1{next_tag('with_top')}"
        )
        filters.append(
            f"[0:v]crop={w}:{bot_h}:0:{h - bot_h},"
            f"format=rgba,colorchannelmixer=aa={bot_op}"
            f"{next_tag('botbar')}"
        )
        filters.append(
            f"[with_top][botbar]overlay=0:H-h:shortest=1{next_tag('bars')}"
        )
        base_tag = "bars"

    # ═══════════════════════════════════════════════════════════
    # SPLIT BARS: 双拼横条（非对称上下）
    # ═══════════════════════════════════════════════════════════
    if config.bars_enabled and config.split_bars_enabled:
        top_h = config.top_bar_height
        bot_h = config.bottom_bar_height
        top_op = config.top_bar_opacity / 100.0
        bot_op = config.bottom_bar_opacity / 100.0
        half_w = w // 2

        # 上半左/右
        filters.append(
            f"[0:v]crop={half_w}:{top_h}:0:0,format=rgba,"
            f"colorchannelmixer=aa={top_op}{next_tag('tl_bar')}"
        )
        filters.append(
            f"[0:v]crop={half_w}:{top_h}:{half_w}:0,format=rgba,"
            f"colorchannelmixer=aa={top_op}{next_tag('tr_bar')}"
        )
        filters.append(
            f"[0:v]crop={half_w}:{bot_h}:0:{h - bot_h},format=rgba,"
            f"colorchannelmixer=aa={bot_op}{next_tag('bl_bar')}"
        )
        filters.append(
            f"[0:v]crop={half_w}:{bot_h}:{half_w}:{h - bot_h},format=rgba,"
            f"colorchannelmixer=aa={bot_op}{next_tag('br_bar')}"
        )
        filters.append(
            f"[{base_tag}][tl_bar]overlay=0:0:shortest=1[s1];"
            f"[s1][tr_bar]overlay={half_w}:0:shortest=1[s2];"
            f"[s2][bl_bar]overlay=0:{h - bot_h}:shortest=1[s3];"
            f"[s3][br_bar]overlay={half_w}:{h - bot_h}:shortest=1"
            f"{next_tag('split_bars')}"
        )
        base_tag = "split_bars"

    # ═══════════════════════════════════════════════════════════
    # LINE: 十字线/横线叠加
    # ═══════════════════════════════════════════════════════════
    if config.line_enabled:
        lo = config.line_opacity / 100.0
        lx = config.line_x / 100.0
        ly = config.line_y / 100.0
        lw = config.line_width

        if "十字" in config.line_style_choice:
            # 十字线: 水平 + 垂直
            h_y = int(h * ly)
            v_x = int(w * lx)
            filters.append(
                f"[{base_tag}]drawbox=x=0:y={h_y}:w={w}:h={lw}:"
                f"color=white@{lo}:t=fill{next_tag('hline')}"
            )
            filters.append(
                f"[hline]drawbox=x={v_x}:y=0:w={lw}:h={h}:"
                f"color=white@{lo}:t=fill{next_tag('cross')}"
            )
            base_tag = "cross"
        else:
            # 仅横线
            h_y = int(h * ly)
            filters.append(
                f"[{base_tag}]drawbox=x=0:y={h_y}:w={w}:h={lw}:"
                f"color=white@{lo}:t=fill{next_tag('lined')}"
            )
            base_tag = "lined"

    # ═══════════════════════════════════════════════════════════
    # PIP 1: 画中画 1 (辅助视频)
    # ═══════════════════════════════════════════════════════════
    if config.pip_enabled:
        pip_scale = config.pip_scale / 100.0
        pip_opacity = config.pip_opacity / 100.0
        pip_x = config.pip_x / 100.0
        pip_y = config.pip_y / 100.0

        # PIP 使用背景视频作为源
        pip_filter = (
            f"[0:v]scale=iw*{pip_scale}:ih*{pip_scale},"
            f"format=rgba,colorchannelmixer=aa={pip_opacity}"
            f"{next_tag('pip1')}"
        )
        filters.append(pip_filter)

        if config.pip_move:
            # 移动 PIP：用表达式控制位置（水平往返）
            filters.append(
                f"[{base_tag}][pip1]overlay="
                f"'(W-w)*{pip_x}+(W-w)*{pip_x}*sin(t/2)':"
                f"(H-h)*{pip_y}:shortest=1"
                f"{next_tag('with_pip1')}"
            )
        else:
            filters.append(
                f"[{base_tag}][pip1]overlay="
                f"(W-w)*{pip_x}:(H-h)*{pip_y}:shortest=1"
                f"{next_tag('with_pip1')}"
            )
        base_tag = "with_pip1"

    # ═══════════════════════════════════════════════════════════
    # PIP 2: 画中画 2
    # ═══════════════════════════════════════════════════════════
    if config.pip2_enabled:
        pip2_scale = config.pip2_scale / 100.0
        pip2_opacity = config.pip2_opacity / 100.0
        pip2_x = config.pip2_x / 100.0
        pip2_y = config.pip2_y / 100.0

        filters.append(
            f"[0:v]scale=iw*{pip2_scale}:ih*{pip2_scale},"
            f"format=rgba,colorchannelmixer=aa={pip2_opacity}"
            f"{next_tag('pip2')}"
        )

        if config.pip2_move:
            filters.append(
                f"[{base_tag}][pip2]overlay="
                f"'(W-w)*{pip2_x}+(W-w)*{pip2_x}*sin(t/2+PI)':"
                f"(H-h)*{pip2_y}:shortest=1"
                f"{next_tag('with_pip2')}"
            )
        else:
            filters.append(
                f"[{base_tag}][pip2]overlay="
                f"(W-w)*{pip2_x}:(H-h)*{pip2_y}:shortest=1"
                f"{next_tag('with_pip2')}"
            )
        base_tag = "with_pip2"

    # ═══════════════════════════════════════════════════════════
    # MOTION: 动态缩放/晃动/抖动
    # ═══════════════════════════════════════════════════════════
    has_motion = config.zoom_amp > 0 or config.sway_amp > 0 or config.shake_amp > 0
    if has_motion:
        zoom_val = 1.0 + config.zoom_amp / 1000.0
        sway_val = config.sway_amp / 100.0
        shake_val = config.shake_amp / 100.0

        # 用 scale + crop 模拟动态效果
        zoom_expr = f"1+{zoom_val - 1.0}*sin(t/3)"
        sway_expr = f"{sway_val}*sin(t/2)"
        shake_expr = f"{shake_val}*(random(1)-0.5)*2"

        filters.append(
            f"[{base_tag}]scale=iw*{zoom_expr}:ih*{zoom_expr},"
            f"crop={w}:{h}:(iw-{w})/2+{sway_expr}+{shake_expr}*w:"
            f"(ih-{h})/2+{shake_expr}*h"
            f"{next_tag('motion')}"
        )
        base_tag = "motion"

    # ═══════════════════════════════════════════════════════════
    # STICKER: 多层贯穿贴纸
    # ═══════════════════════════════════════════════════════════
    # 解析多层配置
    sticker_layer_configs = _parse_layers(config.sticker_layers_json)
    if not sticker_layer_configs:
        # 回退到单层模式
        sticker_layer_configs = [{
            "scale": config.sticker_scale,
            "opacity": config.sticker_opacity,
            "x": config.sticker_x,
            "y": config.sticker_y,
        }]

    if config.sticker_enabled and sticker_files:
        for i, sf in enumerate(sticker_files):
            if not sf or not sf.exists():
                continue
            layer_cfg = sticker_layer_configs[i] if i < len(sticker_layer_configs) else sticker_layer_configs[-1]

            is_video = sf.suffix.lower() in VIDEO_EXTS
            loop_args = ["-stream_loop", "-1"] if is_video else ["-loop", "1"]
            cmd += loop_args + ["-i", str(sf)]
            idx = input_idx
            input_idx += 1

            sc = layer_cfg["scale"] / 100.0
            op = layer_cfg["opacity"] / 100.0
            sx = layer_cfg["x"] / 100.0
            sy = layer_cfg["y"] / 100.0
            tag = f"sticker{i}"

            filters.append(
                f"[{idx}:v]scale=iw*{sc}:ih*{sc},"
                f"format=rgba,colorchannelmixer=aa={op}"
                f"[{tag}]"
            )
            filters.append(
                f"[{base_tag}][{tag}]overlay="
                f"(W-w)*{sx}:(H-h)*{sy}:shortest=1"
                f"[{base_tag}_s{i}]"
            )
            base_tag = f"{base_tag}_s{i}"

    # ═══════════════════════════════════════════════════════════
    # MOVING STICKER: 多层移动贴纸
    # ═══════════════════════════════════════════════════════════
    mover_layer_configs = _parse_layers(config.mover_layers_json)
    if not mover_layer_configs:
        mover_layer_configs = [{
            "scale": config.sticker_scale,
            "opacity": config.sticker_opacity,
            "x": 50, "y": 50,
            "period": config.moving_sticker_period,
        }]

    if config.moving_sticker_enabled and mover_files:
        for i, mf in enumerate(mover_files):
            if not mf or not mf.exists():
                continue
            layer_cfg = mover_layer_configs[i] if i < len(mover_layer_configs) else mover_layer_configs[-1]

            is_video = mf.suffix.lower() in VIDEO_EXTS
            loop_args = ["-stream_loop", "-1"] if is_video else ["-loop", "1"]
            cmd += loop_args + ["-i", str(mf)]
            idx = input_idx
            input_idx += 1

            sc = layer_cfg["scale"] / 100.0
            op = layer_cfg["opacity"] / 100.0
            period = max(1, layer_cfg.get("period", config.moving_sticker_period))
            tag = f"mover{i}"

            filters.append(
                f"[{idx}:v]scale=iw*{sc}:ih*{sc},"
                f"format=rgba,colorchannelmixer=aa={op}"
                f"[{tag}]"
            )
            filters.append(
                f"[{base_tag}][{tag}]overlay="
                f"'(W-w)/2+(W-w)/2*sin(2*PI*t/{period})':"
                f"'(H-h)/2+(H-h)/2*cos(2*PI*t/{period})':shortest=1"
                f"[{base_tag}_m{i}]"
            )
            base_tag = f"{base_tag}_m{i}"

    # ═══════════════════════════════════════════════════════════
    # SCANLIGHT: 扫光效果 (blend=screen)
    # ═══════════════════════════════════════════════════════════
    if config.scanlight_enabled and scanlight_file and scanlight_file.exists():
        cmd += ["-stream_loop", "-1", "-i", str(scanlight_file)]
        sl_idx = input_idx
        input_idx += 1

        sl_opacity = config.scanlight_opacity / 100.0
        sl_speed = config.scanlight_speed / 100.0

        filters.append(
            f"[{sl_idx}:v]scale={w}:{h},"
            f"setpts={1/sl_speed}*PTS,"
            f"format=rgba,colorchannelmixer=aa={sl_opacity}"
            f"{next_tag('scan')}"
        )
        filters.append(
            f"[{base_tag}][scan]blend=all_mode=screen:"
            f"all_opacity={sl_opacity}:shortest=1"
            f"{next_tag('scanned')}"
        )
        base_tag = "scanned"

    # ═══════════════════════════════════════════════════════════
    # KAIMU: 开幕效果
    # ═══════════════════════════════════════════════════════════
    if config.kaimu_enabled:
        speed = config.kaimu_speed / 100.0
        mode = config.kaimu_mode
        duration = 1.5 / speed  # 开幕动画持续时间（秒）

        if "上下" in mode:
            # 上下开幕：从中心线向上下展开
            filters.append(
                f"[{base_tag}]crop={w}:ih*t/{duration}:0:"
                f"(ih-ih*t/{duration})/2:exact=1"
                f"{next_tag('kaimu')}"
            )
        elif "左右" in mode:
            # 左右开幕：从中心线向左右展开
            filters.append(
                f"[{base_tag}]crop=iw*t/{duration}:{h}:"
                f"(iw-iw*t/{duration})/2:0:exact=1"
                f"{next_tag('kaimu')}"
            )
        else:
            # 黑屏开幕：淡入效果
            filters.append(
                f"[{base_tag}]fade=in:0:{int(duration * fps)}"
                f"{next_tag('kaimu')}"
            )

        base_tag = "kaimu"

        # 开幕素材叠加
        if kaimu_file and kaimu_file.exists():
            loop_args = (
                ["-stream_loop", "-1"]
                if kaimu_file.suffix.lower() in VIDEO_EXTS
                else ["-loop", "1"]
            )
            cmd += loop_args + ["-i", str(kaimu_file)]
            km_idx = input_idx
            input_idx += 1

            filters.append(
                f"[{km_idx}:v]scale={w}:{h},format=rgba"
                f"{next_tag('km_mat')}"
            )
            filters.append(
                f"[{base_tag}][km_mat]overlay=0:0:shortest=1"
                f"{next_tag('with_km')}"
            )
            base_tag = "with_km"

    # ═══════════════════════════════════════════════════════════
    # COVER: 封面标题 (drawtext)
    # ═══════════════════════════════════════════════════════════
    if config.cover_enabled:
        if config.cover_follow_name:
            title_text = main_video.stem
        else:
            title_text = config.cover_text or main_video.stem

        font_size = config.cover_size
        # 使用项目自带的字体
        font_path = Path(__file__).parent.parent.parent / "fonts" / "ZCOOLKuaiLe-Regular.ttf"
        font_file = str(font_path) if font_path.exists() else ""

        font_args = f":fontfile='{font_file}'" if font_file else ""
        # 转义特殊字符
        safe_title = title_text.replace("'", "'\\\\''").replace(":", "\\:")
        safe_title = safe_title.replace("%", "\\\\%")

        # 标题居中，位置在开幕动画之上
        filters.append(
            f"[{base_tag}]drawtext=text='{safe_title}':"
            f"fontsize={font_size}:"
            f"fontcolor=white@0.9:"
            f"x=(w-text_w)/2:y=(h-text_h)/2"
            f"{font_args}:"
            f"enable='between(t,0,4)'"
            f"{next_tag('cover')}"
        )
        base_tag = "cover"

    # ═══════════════════════════════════════════════════════════
    # COLOR: 调色 (预设滤镜 + 手动微调 + vignette)
    # ═══════════════════════════════════════════════════════════
    from engine.color_grade import apply_color_adjustments as _color

    filter_frag, new_tag = _color(
        base_tag,
        brightness=config.brightness,
        contrast=config.contrast,
        saturation=config.saturation,
        temperature=config.temperature,
        vignette=config.vignette,
        filter_name=getattr(config, "filter_name", ""),
        filter_strength=getattr(config, "filter_strength", 100),
    )
    if filter_frag:
        filters.append(filter_frag)
        base_tag = new_tag

    # 暗角 (vignette) - 作为独立后处理
    vig = config.vignette / 100.0
    if vig > 0.01:
        vig_strength = min(vig, 0.85)
        filters.append(
            f"[{base_tag}]format=rgba[vic];"
            f"color=black@{vig_strength:.2f}:size={w}x{h},"
            f"format=rgba[vignette];"
            f"[vic][vignette]overlay=0:0:shortest=1"
            f"{next_tag('vignetted')}"
        )
        base_tag = "vignetted"

    # ═══════════════════════════════════════════════════════════
    # OUTPUT: 格式转换 + 编码
    # ═══════════════════════════════════════════════════════════
    filters.append(f"[{base_tag}]format=yuv420p[next_v]")

    # 选择编码器
    if config.gpu:
        if config.hevc:
            encoder = "hevc_nvenc"
        else:
            encoder = "h264_nvenc"
    else:
        if config.hevc:
            encoder = "libx265"
        else:
            encoder = "libx264"

    filter_complex = ";".join(filters)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[next_v]",
        "-map", "1:a?",
        "-c:v", encoder,
        "-preset", config.preset,
        "-crf", str(config.crf),
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", str(fps),
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    return cmd


def _parse_layers(json_str: str) -> List[dict]:
    """解析贴纸层 JSON 配置字符串。"""
    if not json_str or not json_str.strip():
        return []
    try:
        layers = json.loads(json_str)
        if isinstance(layers, list):
            return layers
    except (json.JSONDecodeError, TypeError):
        pass
    return []
