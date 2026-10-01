"""源码开发用算法等价实现；正式 Nuitka 构建明确排除本模块。"""

from __future__ import annotations

import math
import random


FILTER_PRESETS = {
    "晴川": (0.05, 1.05, 1.10, 7500, 1.02, 1.05, 1.08),
    "暖阳": (0.08, 1.02, 1.15, 9000, 1.10, 1.05, 0.95),
    "复古": (-0.03, 1.10, 0.65, 8000, 1.12, 1.02, 0.90),
    "黑白": (0.00, 1.15, 0.00, 6500, 1.00, 1.00, 1.00),
    "冷色": (-0.02, 1.05, 0.95, 4000, 0.95, 1.00, 1.10),
    "胶片": (0.02, 1.08, 0.85, 7000, 1.04, 1.02, 1.06),
    "鲜明": (0.05, 1.12, 1.20, 6500, 1.00, 1.00, 1.00),
    "淡雅": (0.10, 0.95, 0.85, 5500, 1.02, 1.04, 1.03),
}


def _rng(seed):
    return random.SystemRandom() if seed is None else random.Random(seed)


def playback_rate(minimum, maximum, seed=None):
    lo, hi = sorted((max(0.5, min(2.0, float(minimum))),
                     max(0.5, min(2.0, float(maximum)))))
    return _rng(seed).uniform(lo, hi)


def filter_segments(count, seed=None):
    rng = _rng(seed)
    names = tuple(FILTER_PRESETS)
    result = []
    for _ in range(max(1, min(20, int(count)))):
        choices = [name for name in names if not result or name != result[-1]]
        result.append(rng.choice(choices))
    return result


def color_adjustments_filter(base_tag, brightness=0, contrast=0, saturation=0,
                             temperature=0, filter_name="", filter_strength=100):
    filters = []
    preset = FILTER_PRESETS.get(filter_name)
    if preset:
        pb, pc, ps, pt, pr, pg, pblue = preset
        strength = filter_strength / 100.0
        eq = []
        b = pb * strength
        c = 1.0 + (pc - 1.0) * strength
        s = 1.0 + (ps - 1.0) * strength
        temp = int(6500 + (pt - 6500) * strength)
        if abs(b) > 0.005:
            eq.append(f"brightness={b:.2f}")
        if abs(c - 1.0) > 0.005:
            eq.append(f"contrast={c:.2f}")
        if abs(s - 1.0) > 0.005:
            eq.append(f"saturation={s:.2f}")
        if eq:
            filters.append("eq=" + ":".join(eq))
        if abs(temp - 6500) > 50:
            shift = max(-1.0, min(1.0, (temp - 6500) / 3000))
            filters.append(f"colorbalance=rh={shift * .12:.3f}:bh={-shift * .12:.3f}")
        gamma = []
        for channel, value in (("r", pr), ("g", pg), ("b", pblue)):
            value = 1.0 + (value - 1.0) * strength
            if abs(value - 1.0) > 0.005:
                gamma.append(f"{channel}h={value - 1.0:.2f}")
        if gamma:
            filters.append("colorbalance=" + ":".join(gamma))

    eq = []
    if abs(brightness / 100.0) > 0.005:
        eq.append(f"brightness={brightness / 100.0:.2f}")
    if abs(contrast) > 0.5:
        eq.append(f"contrast={1.0 + contrast / 100.0:.2f}")
    if abs(saturation) > 0.5:
        eq.append(f"saturation={1.0 + saturation / 100.0:.2f}")
    if eq:
        filters.append("eq=" + ":".join(eq))
    if abs(temperature) > 1:
        shift = temperature / 100.0
        filters.append(f"colorbalance=rh={shift * .12:.3f}:bh={-shift * .12:.3f}")
    if not filters:
        return "", base_tag
    output = base_tag + "_colored"
    return f"[{base_tag}]" + ",".join(filters) + f"[{output}]", output


def mild_voice_filters(input_tag, duration, seed=None):
    rng = _rng(seed)
    p = {
        "pitch": rng.uniform(1.0040, 1.0050), "bass": rng.uniform(0.45, 1.00),
        "treble": -rng.uniform(0.35, 1.00), "noise": rng.uniform(-52.0, -50.0),
        "ratio": rng.uniform(1.30, 1.40), "attack": rng.uniform(15.0, 20.0),
        "release": rng.uniform(145.0, 180.0), "makeup": rng.uniform(0.70, 1.00),
        "echo_out": rng.uniform(0.82, 0.86), "echo_delay": rng.uniform(18.0, 26.0),
        "echo_decay": rng.uniform(0.045, 0.050), "stereo": rng.uniform(1.040, 1.050),
        "lufs": rng.uniform(-16.0, -15.5), "peak": rng.uniform(-1.5, -1.3),
        "lra": rng.uniform(10.0, 11.0), "limiter": rng.uniform(0.95, 0.97),
    }
    duration = max(0.0, float(duration))
    filters = [f"[{input_tag}]aformat=sample_rates=44100:channel_layouts=stereo[mild_input]"]
    source = "mild_input"
    compensation = 1.0
    if duration > 0:
        count = max(1, math.ceil(duration / 10.0))
        sources = [source]
        if count > 1:
            sources = [f"mild_src_{i}" for i in range(count)]
            filters.append(f"[{source}]asplit={count}" + "".join(f"[{x}]" for x in sources))
        tags, joined = [], 0.0
        for i, item in enumerate(sources):
            start = i * 10.0
            length = min(10.0, duration - start)
            rate = rng.uniform(1.010, 1.026) if i % 2 == 0 else rng.uniform(0.974, 0.990)
            tag = f"mild_seg_{i}"
            filters.append(f"[{item}]atrim=start={start:.6f}:duration={length:.6f},"
                           f"asetpts=PTS-STARTPTS,atempo={rate:.9f}[{tag}]")
            tags.append(tag)
            joined += length / rate
        if len(tags) > 1:
            filters.append("".join(f"[{x}]" for x in tags)
                           + f"concat=n={len(tags)}:v=0:a=1[mild_joined]")
            source = "mild_joined"
        else:
            source = tags[0]
        compensation = joined / duration
    pitch = p["pitch"]
    chain = (
        f"[{source}]atempo={compensation:.10f},asetrate=44100*{pitch:.9f},"
        f"aresample=44100,atempo={1 / pitch:.9f},bass=g={p['bass']:.5f}:f=120:w=0.6,"
        f"treble=g={p['treble']:.5f}:f=4500:w=0.5,afftdn=nf={p['noise']:.4f},"
        f"acompressor=threshold=-20dB:ratio={p['ratio']:.5f}:attack={p['attack']:.4f}:"
        f"release={p['release']:.4f}:makeup={p['makeup']:.4f}dB,"
        f"aecho=0.8:{p['echo_out']:.5f}:{p['echo_delay']:.4f}:{p['echo_decay']:.6f},"
        f"stereotools=mlev=1:slev={p['stereo']:.6f},"
        f"loudnorm=I={p['lufs']:.4f}:TP={p['peak']:.4f}:LRA={p['lra']:.4f},"
        f"alimiter=limit={p['limiter']:.6f}"
        + (f",apad,atrim=duration={duration:.9f}" if duration > 0 else "")
        + "[dialogue]"
    )
    filters.append(chain)
    return filters, "dialogue"


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
