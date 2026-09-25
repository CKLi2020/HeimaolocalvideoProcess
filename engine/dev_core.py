"""源码开发用算法等价实现；正式 Nuitka 构建明确排除本模块。"""

from __future__ import annotations


def mask_alpha(w, h, feather, margin_tb, margin_lr):
    d = max(1, round(feather * min(w, h) / 1080.0))
    offset = d / 2
    parts = []
    if margin_lr > 0:
        parts += [
            f"clip((X-W*{margin_lr}+{offset})/{d},0,1)",
            f"clip((W*(1-{margin_lr})-X+{offset})/{d},0,1)",
        ]
    if margin_tb > 0:
        parts += [
            f"clip((Y-H*{margin_tb}+{offset})/{d},0,1)",
            f"clip((H*(1-{margin_tb})-Y+{offset})/{d},0,1)",
        ]
    if not parts:
        return ""
    inner = parts[0]
    for part in parts[1:]:
        inner = f"min({inner},{part})"
    return f"255*{inner}"


def butterfly_plan(duration, head, hidden=None, fps=30):
    hidden_value = duration + 0.0667 if hidden is None else float(hidden)
    chunks = [23.0] * int(hidden_value // 23.0)
    remainder = hidden_value - sum(chunks)
    if remainder > 0.02:
        chunks.append(remainder)
    return {
        "hidden": hidden_value,
        "chunks": chunks,
        "jump_frame": round((head + hidden_value) * fps),
        "main_frames": round(duration * fps),
    }


def window_matte_chain(canvas_width, canvas_height, center_x, center_y,
                       window_width, window_height, feather):
    d = max(1, round(feather * min(canvas_width, canvas_height) / 1080.0))
    left = canvas_width * (center_x - window_width / 2) / 100
    top = canvas_height * (center_y - window_height / 2) / 100
    box_width = max(1, round(canvas_width * window_width / 100))
    box_height = max(1, round(canvas_height * window_height / 100))

    def axis(size, value, span):
        delta = value - span / 2
        return f"{size}/2{'+' if delta >= 0 else '-'}{abs(delta):g}"

    blur = max(1, round((d - 1) / 2))
    return (
        "format=gray,lutyuv=y=0,"
        f"drawbox=x={axis('iw', left, canvas_width)}:"
        f"y={axis('ih', top, canvas_height)}:w={box_width}:h={box_height}:"
        "color=white:t=fill,lutyuv=y='if(gt(val,128),255,0)',"
        f"boxblur={blur}:1"
    )


def concat_filter_segment(index, duration, has_audio, width, height, fps):
    video = (
        f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},"
        f"format=yuv420p,trim=duration={duration:g},setpts=PTS-STARTPTS[v{index}]"
    )
    if has_audio:
        audio = (
            f"[{index}:a]aresample=48000,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"atrim=duration={duration:g},asetpts=PTS-STARTPTS[a{index}]"
        )
    else:
        audio = (
            "anullsrc=r=48000:cl=stereo,"
            f"atrim=duration={duration:g},asetpts=PTS-STARTPTS[a{index}]"
        )
    return video, audio
