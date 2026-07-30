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
        if aux_scale_val > 1:
            bg_filter_parts.append(f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2")
        else:
            bg_filter_parts.append(f"pad={w}:{h}:({w}-iw)/2:({h}-ih)/2:black")
    bg_filter_parts.append(f"fps={fps}")

    filters.append(f"[0:v]{','.join(bg_filter_parts)}{next_tag('bg')}")

    # ═══════════════════════════════════════════════════════════
    # INPUT 1: Main video — 完全匹配参考软件逻辑
    # ═══════════════════════════════════════════════════════════
    cmd += ["-i", str(main_video)]
    input_idx = 2

    if config.main_fit:
        # 参考软件逻辑：先按用户比例缩放，再缩小适配画布（不超出）
        # 主视频始终在画布内，背景视频在上下方可见
        main_filter = (
            f"[1:v]scale=iw*{main_scale}:ih*{main_scale},"
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"fps={fps},format=rgba{next_tag('main')}"
        )
    else:
        # 强制填满：increase+crop 确保画布无黑边
        main_filter = (
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"scale=iw*{main_scale}:ih*{main_scale},"
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

        edge = max(1, int(feather * min(w, h) / 500))
        filters.append(
            f"[base]drawbox=x=0:y=0:w={w}:h={my + edge}:color=black@0.65:t=fill,"
            f"drawbox=x=0:y={h - my - edge}:w={w}:h={my + edge}:color=black@0.65:t=fill,"
            f"drawbox=x=0:y=0:w={mx + edge}:h={h}:color=black@0.65:t=fill,"
            f"drawbox=x={w - mx - edge}:y=0:w={mx + edge}:h={h}:color=black@0.65:t=fill"
            f"{next_tag('masked')}"
        )
        current_tag = "masked"

    base_tag = current_tag

    # ═══════════════════════════════════════════════════════════
    # TOP MATTE: 顶部蒙版叠层 (独立于横条)
    # ═══════════════════════════════════════════════════════════
    if config.top_step_enabled and config.top_scale > 0:
        ts = config.top_scale / 100.0
        to = config.top_opacity / 100.0
        tf = config.top_feather
        if ts >= 1:
            top_size = (
                f"scale={int(w * ts)}:{int(h * ts)},"
                f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2"
            )
        else:
            top_size = (
                f"scale={max(2, int(w * ts))}:{max(2, int(h * ts))},"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0"
            )
        filters.append(
            f"[0:v]{top_size},"
            f"format=rgba,gblur=sigma={max(0.1, tf / 10):.2f},"
            f"colorchannelmixer=aa={to}"
            f"{next_tag('topmat')}"
        )
        filters.append(
            f"[{base_tag}][topmat]overlay=0:0:shortest=1{next_tag('matted')}"
        )
        base_tag = "matted"

    # ═══════════════════════════════════════════════════════════
    # BARS: 顶底横条 — 参考软件逻辑：背景视频裁剪 + alpha 叠加
    # ═══════════════════════════════════════════════════════════
    if config.bars_enabled:
        top_h_use = config.top_bar_height if config.split_bars_enabled else config.bar_height
        top_op = (config.top_bar_opacity if config.split_bars_enabled else config.bar_opacity) / 100.0
        bot_h_use = config.bottom_bar_height if config.split_bars_enabled else config.bar_height
        bot_op = (config.bottom_bar_opacity if config.split_bars_enabled else config.bar_opacity) / 100.0

        top_h_use = min(top_h_use, h)
        bot_h_use = min(bot_h_use, h)

        # 顶部横条：从 [0:v] 重新处理背景 → 裁切顶部区域 → alpha 混合叠加
        if top_h_use > 0:
            filters.append(
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},crop={w}:{top_h_use}:0:0,"
                f"format=rgba,colorchannelmixer=aa={top_op}"
                f"{next_tag('topbar')}"
            )
            filters.append(
                f"[{base_tag}][topbar]overlay=0:0:shortest=1{next_tag('bars_t')}"
            )
            base_tag = "bars_t"

        # 底部横条：同理
        if bot_h_use > 0:
            filters.append(
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},crop={w}:{bot_h_use}:0:{h - bot_h_use},"
                f"format=rgba,colorchannelmixer=aa={bot_op}"
                f"{next_tag('botbar')}"
            )
            filters.append(
                f"[{base_tag}][botbar]overlay=0:{h - bot_h_use}:shortest=1"
                f"{next_tag('bars')}"
            )
            base_tag = "bars"

        # 顶部羽化：半透明黑色渐变
        feather_h = max(1, config.top_bar_feather_down)
        if feather_h > 0 and top_op > 0.05:
            fop = min(top_op * 0.6, 0.9)
            filters.append(
                f"[{base_tag}]drawbox=x=0:y={max(0, top_h_use - feather_h)}:"
                f"w={w}:h={feather_h}:"
                f"color=black@{fop}:t=fill{next_tag('bars_tf')}"
            )
            base_tag = "bars_tf"

        # 底部羽化
        feather_h = max(1, config.bottom_bar_feather_up)
        if feather_h > 0 and bot_op > 0.05:
            fop = min(bot_op * 0.6, 0.9)
            filters.append(
                f"[{base_tag}]drawbox=x=0:y={h - bot_h_use}:w={w}:h={feather_h}:"
                f"color=black@{fop}:t=fill{next_tag('bars_bf')}"
            )
            base_tag = "bars_bf"

        if config.split_bars_enabled:
            split = max(1, config.tb_split_feather or config.split_feather)
            if split > 0:
                filters.append(
                    f"[{base_tag}]drawbox=x={(w - split) // 2}:y=0:w={split}:h={top_h_use}:"
                    f"color=black@0.35:t=fill,"
                    f"drawbox=x={(w - max(1, config.bb_split_feather or config.split_feather)) // 2}:"
                    f"y={h - bot_h_use}:w={max(1, config.bb_split_feather or config.split_feather)}:h={bot_h_use}:"
                    f"color=black@0.35:t=fill{next_tag('bars_split')}"
                )
                base_tag = "bars_split"

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
            period = max(0.2, 10 / max(1, config.pip_move_speed))
            # 移动 PIP：用表达式控制位置（水平往返）
            filters.append(
                f"[{base_tag}][pip1]overlay="
                f"'(W-w)*{pip_x}+(W-w)*{pip_x}*sin(t/{period:.3f})':"
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
            period = max(0.2, 10 / max(1, config.pip2_move_speed))
            filters.append(
                f"[{base_tag}][pip2]overlay="
                f"'(W-w)*{pip2_x}+(W-w)*{pip2_x}*sin(t/{period:.3f}+PI)':"
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
        sway_val = config.sway_amp / 100.0
        shake_val = config.shake_amp / 100.0

        # 留足裁切余量，再在放大画面内移动；避免动态表达式产生小于画布的帧。
        scale_factor = 1 + config.zoom_amp / 100.0 + 2 * sway_val + 2 * shake_val
        sway_expr = f"{sway_val}*iw*sin(t/2)"
        shake_expr = f"{shake_val}*(random(1)-0.5)*2"

        filters.append(
            f"[{base_tag}]scale=iw*{scale_factor:.4f}:ih*{scale_factor:.4f},"
            f"crop={w}:{h}:(iw-{w})/2+{sway_expr}+{shake_expr}*iw:"
            f"(ih-{h})/2+{shake_expr}*ih"
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
    # 参考软件坐标系：-100~100，0=居中，负数=从对边算
    _use_ref_coords = any(
        layer.get("x", 0) < 0 or layer.get("y", 0) < 0
        for layer in sticker_layer_configs
    )
    sticker_layer_count = len(sticker_layer_configs)
    sticker_group_count = max(
        1, (len(sticker_files or []) + sticker_layer_count - 1) // sticker_layer_count
    )

    if config.sticker_enabled and sticker_files:
        for i, sf in enumerate(sticker_files):
            if not sf or not sf.exists():
                continue
            layer_cfg = sticker_layer_configs[i % sticker_layer_count]

            is_stream = sf.suffix.lower() in VIDEO_EXTS | {".gif"}
            loop_args = ["-stream_loop", "-1"] if is_stream else ["-loop", "1"]
            cmd += loop_args + ["-i", str(sf)]
            idx = input_idx
            input_idx += 1

            sc = layer_cfg["scale"] / 100.0
            op = layer_cfg["opacity"] / 100.0
            if _use_ref_coords:
                sx = (layer_cfg["x"] + 50) / 100.0
                sy = (layer_cfg["y"] + 50) / 100.0
            else:
                sx = layer_cfg["x"] / 100.0
                sy = layer_cfg["y"] / 100.0
            tag = f"sticker{i}"

            filters.append(
                f"[{idx}:v]scale=iw*{sc}:ih*{sc},"
                f"format=rgba,colorchannelmixer=aa={op}"
                f"[{tag}]"
            )
            switch = ""
            if config.sticker_switch_sec > 0 and sticker_group_count > 1:
                group = i // sticker_layer_count
                start = group * config.sticker_switch_sec
                end = (group + 1) * config.sticker_switch_sec
                cycle = sticker_group_count * config.sticker_switch_sec
                switch = f":enable='between(mod(t,{cycle}),{start},{end})'"
            filters.append(
                f"[{base_tag}][{tag}]overlay="
                f"(W-w)*{sx}:(H-h)*{sy}:shortest=1{switch}"
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
        _mover_use_ref = any(
            l.get("x", 0) < 0 or l.get("y", 0) < 0
            for l in mover_layer_configs
        )
        for i, mf in enumerate(mover_files):
            if not mf or not mf.exists():
                continue
            layer_cfg = mover_layer_configs[i] if i < len(mover_layer_configs) else mover_layer_configs[-1]

            is_stream = mf.suffix.lower() in VIDEO_EXTS | {".gif"}
            loop_args = ["-stream_loop", "-1"] if is_stream else ["-loop", "1"]
            cmd += loop_args + ["-i", str(mf)]
            idx = input_idx
            input_idx += 1

            sc = layer_cfg["scale"] / 100.0
            op = layer_cfg["opacity"] / 100.0
            period = max(1, layer_cfg.get("period", config.moving_sticker_period))
            tag = f"mover{i}"

            if _mover_use_ref:
                mx = (layer_cfg["x"] + 100) / 200.0
                my = (layer_cfg["y"] + 100) / 200.0
            else:
                mx = layer_cfg.get("x", 50) / 100.0
                my = layer_cfg.get("y", 50) / 100.0

            filters.append(
                f"[{idx}:v]scale=iw*{sc}:ih*{sc},"
                f"format=rgba,colorchannelmixer=aa={op}"
                f"[{tag}]"
            )
            filters.append(
                f"[{base_tag}][{tag}]overlay="
                f"'(W-w)*{mx}+(W-w)*{mx}*sin(2*PI*t/{period})':"
                f"'(H-h)*{my}+(H-h)*{my}*cos(2*PI*t/{period})':shortest=1"
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
            f"format=gbrp"
            f"{next_tag('scan')}"
        )
        filters.append(
            f"[{base_tag}]format=gbrp[scan_base];"
            f"[scan_base][scan]blend=all_mode=screen:"
            f"all_opacity={sl_opacity}:shortest=1"
            f"{next_tag('scanned')}"
        )
        base_tag = "scanned"

    # ═══════════════════════════════════════════════════════════
    # KAIMU: 开幕效果
    # ═══════════════════════════════════════════════════════════
    if config.kaimu_enabled:
        speed = max(0.1, config.kaimu_speed / 100.0)
        mode = config.kaimu_mode
        duration = 1.5 / speed
        transition = (
            "vertopen" if "上下" in mode
            else "horzopen" if "左右" in mode
            else "fadeblack"
        )

        # 素材模式从封面素材平滑过渡到成片；其余模式从黑场开幕。
        if "素材" in mode and kaimu_file and kaimu_file.exists():
            loop_args = (
                ["-stream_loop", "-1"]
                if kaimu_file.suffix.lower() in VIDEO_EXTS | {".gif"}
                else ["-loop", "1"]
            )
            cmd += loop_args + ["-i", str(kaimu_file)]
            km_idx = input_idx
            input_idx += 1

            filters.append(
                f"[{km_idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},fps={fps},format=yuv420p,"
                f"settb=AVTB,setpts=PTS-STARTPTS[km_open]"
            )
            opening_tag = "km_open"
            transition = "fade"
        else:
            filters.append(
                f"color=c=black:s={w}x{h}:r={fps}:d={duration + 1:.3f},"
                f"format=yuv420p,settb=AVTB[kaimu_black]"
            )
            opening_tag = "kaimu_black"

        filters.append(
            f"[{base_tag}]format=yuv420p,settb=AVTB,"
            f"setpts=PTS-STARTPTS[kaimu_content];"
            f"[{opening_tag}][kaimu_content]xfade=transition={transition}:"
            f"duration={duration:.3f}:offset=0{next_tag('kaimu')}"
        )
        base_tag = "kaimu"

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
            f"x=(w-text_w)/2:y=(h-text_h)*{config.cover_y / 100:.3f}"
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
        filter_name=config.filter_name,
        filter_strength=config.filter_strength,
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
        "-threads", str(max(1, config.compose_threads)),
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
