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
from typing import TYPE_CHECKING, List, Optional, Tuple

from config import AppConfig
from engine.auth import mask_alpha

if TYPE_CHECKING:  # 仅用于类型标注，避免与 template_lib 形成运行时循环导入
    from engine.template_lib import Window

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

# 移动贴纸在没有任何显式参数时的默认位置（界面新增一行也用它）。
# 用负值是为了走 (x+100)/200 那套换算，-50 正好是半个画幅的振幅，
# 换算细节见 build_mover_layers 的注释。
DEFAULT_MOVER_X = -50.0
DEFAULT_MOVER_Y = -50.0


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
    background_video: Optional[Path],
    output_path: Path,
    sticker_files: Optional[List[Path]] = None,
    scanlight_file: Optional[Path] = None,
    kaimu_file: Optional[Path] = None,
    mover_files: Optional[List[Path]] = None,
    template_window: Optional["Window"] = None,
    mover_layers: Optional[List[dict]] = None,
) -> List[str]:
    """构建完整的 ffmpeg 命令行。

    Args:
        config: 应用配置
        main_video: 主视频路径
        background_video: 背景视频路径。None 表示没有背景素材（也没开模板），
            此时用纯色画布兜底，仍然出片。
        output_path: 输出路径
        sticker_file: 贴纸文件（图片或视频）
        scanlight_file: 扫光视频文件
        kaimu_file: 开幕素材文件
        mover_file: 移动贴纸文件
        mover_layers: 本次要用的移动贴纸轨道（每项含 scale/opacity/x/y/period），
            由 build_mover_layers 产出。给出时覆盖 config.mover_layers_json ——
            「每次随机轨道」掷出的位置是**每次出片**各掷一次的，掷出来的结果必须
            随任务一起传进来，否则预览和成品会对不上（预览若自己重掷，调一个
            无关参数都会看到贴纸跳位置）。
        template_window: 模板窗口几何；给出时背景槽应传入模板视频，模板盖在
            主视频之上，只有窗口区域（边缘羽化）露出主视频。主视频的尺寸与
            位置不受模板影响。None 表示无模板，行为与历史版本逐字节一致。

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

    if background_video is None:
        # 没有背景素材（也没开模板）时用纯色画布兜底。界面上已经没有
        # 「辅助视频文件夹」入口，这条保证任何开关组合都出得了片。
        # 用 lavfi 的 color 源：它本身就是无限长的，不需要也不能带
        # -stream_loop（那是给文件解复用器的输入选项）。
        # 后面的 bg_filter_parts 照常作用在它上面——缩放/裁切对一块纯色
        # 是空操作，aux_scale/aux_speed 不会因此失效或报错。
        cmd += ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}"]
    else:
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

    # 模板不改主视频的尺寸：模板只是盖在画布上的一层，窗口几何写在 alpha 里
    # （见下方 window_matte）。所以这里的缩放永远只按画布来，与无模板时一致。
    main_tag = "main_raw" if (config.mask_enabled or template_window is not None) else "main"
    if config.main_fit:
        # 参考软件逻辑：先按用户比例缩放，再缩小适配画布（不超出）
        # 主视频始终在画布内，背景视频在上下方可见
        main_filter = (
            f"[1:v]scale=iw*{main_scale}:ih*{main_scale},"
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"fps={fps},format=rgba[{main_tag}]"
        )
    else:
        # 强制填满：increase+crop 确保无黑边
        main_filter = (
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"scale=iw*{main_scale}:ih*{main_scale},"
            f"fps={fps},format=rgba[{main_tag}]"
        )
    filters.append(main_filter)

    # ── 主视频 alpha ──
    # 三条路：只开蒙版（历史路径，逐字节不变）、只开模板（几何蒙版，快）、
    # 两个都开（几何蒙版打底，再用 geq 把用户蒙版乘上去）。
    user_mask = ""
    if config.mask_enabled:
        user_mask = mask_alpha(w, h, config.mask_feather,
                               config.mask_margin_tb / 100.0,
                               config.mask_margin_lr / 100.0)

    if template_window is not None:
        # 延迟导入：template_lib 只在函数内导入本模块，顶层导入会形成环
        from engine.template_lib import window_matte

        matte = window_matte(template_window, (w, h))
        # 窗口蒙版是**几何**做法：drawbox 画出窗口、boxblur 抹出羽化带。
        # 这里刻意不用 geq —— 全屏 geq 实测把渲染拖慢到 4.4 倍，而这条约 1.4 倍。
        filters.append("[main_raw]split=2[tpl_src][tpl_geo]")
        filters.append(f"[tpl_geo]{matte.chain}[tpl_matte]")
        filters.append(
            f"[tpl_src][tpl_matte]alphamerge[{'tpl_win' if user_mask else 'main'}]"
        )
        if user_mask:
            # 用户蒙版要与窗口取交集，而这次 geq 会整块覆写 alpha，
            # 必须把进来的 alpha 乘回去：alpha(X,Y) 读的就是输入 alpha。
            # 只在这条组合路径上用 geq，单纯模板模式下没有这笔开销。
            filters.append(
                f"[tpl_win]geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='{user_mask}*alpha(X,Y)/255'[main]"
            )
    elif user_mask:
        filters.append(
            f"[main_raw]geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{user_mask}'[main]"
        )
    elif config.mask_enabled:
        filters.append("[main_raw]null[main]")

    # ── Overlay main on background ──
    # 主视频始终居中铺在背景/模板上；模板模式下的窗口几何已经写进主视频的
    # alpha，不再影响定位，所以两种情况共用一条表达式（也保证了无模板时
    # 与历史版本逐字节相同）。
    filters.append(
        f"[bg][main]overlay=(W-w)/2:(H-h)/2:shortest=1{next_tag('base')}"
    )

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
    # MOTION: 只先处理基础画面，避免裁掉后加的横条和贴纸
    # ═══════════════════════════════════════════════════════════
    has_motion = config.zoom_amp > 0 or config.sway_amp > 0 or config.shake_amp > 0
    if has_motion:
        zoom_val = config.zoom_amp / 1000.0
        sway_val = config.sway_amp / 1000.0
        shake_val = config.shake_amp / 1000.0
        scale_factor = 1 + zoom_val + 2 * sway_val + 2 * shake_val
        sway_x = f"{sway_val}*iw*sin(t/2)"
        shake_x = f"{shake_val}*iw*sin(7*t)"
        shake_y = f"{shake_val}*ih*cos(5*t)"

        filters.append(
            f"[{base_tag}]scale=iw*{scale_factor:.4f}:ih*{scale_factor:.4f},"
            f"crop={w}:{h}:(iw-{w})/2+{sway_x}+{shake_x}:"
            f"(ih-{h})/2+{shake_y}"
            f"{next_tag('motion')}"
        )
        base_tag = "motion"

    # ═══════════════════════════════════════════════════════════
    # BARS: 顶底横条 — 参考软件逻辑：背景视频裁剪 + alpha 叠加
    # ═══════════════════════════════════════════════════════════
    if config.bars_enabled:
        top_h_use = config.top_bar_height
        top_op = config.top_bar_opacity / 100.0
        bot_h_use = config.bottom_bar_height
        bot_op = config.bottom_bar_opacity / 100.0

        top_h_use = min(top_h_use, h)
        bot_h_use = min(bot_h_use, h)
        top_feather = max(1, min(config.top_bar_feather_down, top_h_use))
        bot_feather = max(1, min(config.bottom_bar_feather_up, bot_h_use))

        # 顶部横条：从 [0:v] 重新处理背景 → 裁切顶部区域 → alpha 混合叠加
        if top_h_use > 0:
            filters.append(
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},crop={w}:{top_h_use}:0:0,"
                f"gblur=sigma={top_feather / 10:.2f},format=rgba,geq="
                f"r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='255*{top_op}*min(1,(H-Y)/{top_feather})'"
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
                f"gblur=sigma={bot_feather / 10:.2f},format=rgba,geq="
                f"r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='255*{bot_op}*min(1,(Y+1)/{bot_feather})'"
                f"{next_tag('botbar')}"
            )
            filters.append(
                f"[{base_tag}][botbar]overlay=0:{h - bot_h_use}:shortest=1"
                f"{next_tag('bars')}"
            )
            base_tag = "bars"

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

        # PIP 取主视频（[1:v]）作源。原先取 [0:v]（背景），而背景本就铺满画布，
        # 把背景缩小后按半透明盖回背景自身，在纯色区域数学上恒等于无变化 ——
        # 该功能等于失效，test_effect_matrix 的 pip1 用例因此测不出像素差异。
        pip_filter = (
            f"[1:v]scale=iw*{pip_scale}:ih*{pip_scale},"
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

        # 同 PIP 1：取主视频作源，而非背景
        filters.append(
            f"[1:v]scale=iw*{pip2_scale}:ih*{pip2_scale},"
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
    mover_layer_configs = mover_layers or _parse_layers(config.mover_layers_json)
    if not mover_layer_configs:
        # 直接调这个函数时没给轨道（出片管线和预览都会给），退回配置里的数量与
        # 默认观感。位置不掷：静态调用两次应该得到同一条命令。
        mover_layer_configs = build_mover_layers(
            1, [], config.mover_scale, config.mover_opacity,
            config.moving_sticker_period,
        )

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


def build_mover_layers(
    count: int,
    base_layers: List[dict],
    default_scale: int,
    default_opacity: int,
    default_period: int,
    roll_positions: bool = False,
) -> List[dict]:
    """本次要用的 count 条移动贴纸轨道。

    这是移动贴纸**唯一**的轨道来源：出片管线、预览、界面上的数量滑条都调它，
    所以「界面上看到几行」和「片子里出几个」不会各说各话。

    把 base_layers 补齐/裁剪成 count 条：base_layers 是界面上那几行（存在
    config.mover_layers_json 里），短了按 i % len 循环取参数补足，长了截掉。
    补出来的行沿用被复制那一行的缩放/不透明度/周期，位置用 DEFAULT_MOVER_X/Y。

    roll_positions=True 时**只重掷水平/垂直位置**（每次出片各掷一次，所以同一
    批素材连跑两次走位不一样），缩放/不透明度/周期一律按传进来的值走 ——
    界面上填什么就是什么，不被悄悄改掉。

    x/y 为什么掷成负值
    -----------------
    mover 段里只要有任意一层的 x 或 y 小于 0，整体就切到 (x+100)/200 这套
    换算（`_mover_use_ref`）。而 overlay 的位置是 (W-w)*m*(1±sin)，即贴纸在
    「(W-w)*m*(1-1)=0」到「(W-w)*m*2」之间来回。m∈(0,0.5] 正好能把整幅画面
    铺开：m 接近 0.5 振幅拉满，接近 0 就几乎不动。所以 x 取 (-95,-5) →
    m∈(0.025,0.475)，几个贴纸不会挤在一处，也不会甩出画面。
    """
    layers: List[dict] = []
    for i in range(max(1, count)):
        base = base_layers[i % len(base_layers)] if base_layers else {}
        layer = {
            "scale": int(base.get("scale", default_scale)),
            "opacity": int(base.get("opacity", default_opacity)),
            "period": max(1, int(base.get("period", default_period))),
            "x": float(base.get("x", DEFAULT_MOVER_X)),
            "y": float(base.get("y", DEFAULT_MOVER_Y)),
        }
        if roll_positions:
            layer["x"] = round(random.uniform(-95.0, -5.0), 1)
            layer["y"] = round(random.uniform(-95.0, -5.0), 1)
        layers.append(layer)
    return layers
