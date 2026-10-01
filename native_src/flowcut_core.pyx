# cython: language_level=3, binding=False, embedsignature=False
"""月落@苍狼原生算法核心。

发布构建会把本模块编译成扩展模块，再由 VMProtect Ultra 单独保护。
这里仅保留稳定、纯计算的核心步骤，文件遍历和进程调度仍由 Python 负责。
"""

import builtins
import math
import random


cdef extern from "VMProtectSDK.h":
    void VMProtectBeginUltra(const char *name)
    void VMProtectEnd()


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


def playback_rate(minimum, maximum, seed=None):
    VMProtectBeginUltra(b"FCALGO:random.playback")
    rng = random.SystemRandom() if seed is None else random.Random(seed)
    lo, hi = sorted((max(0.5, min(2.0, float(minimum))),
                     max(0.5, min(2.0, float(maximum)))))
    result = rng.uniform(lo, hi)
    VMProtectEnd()
    return result


def filter_segments(count, seed=None):
    VMProtectBeginUltra(b"FCALGO:random.filter")
    rng = random.SystemRandom() if seed is None else random.Random(seed)
    names = tuple(FILTER_PRESETS)
    result = []
    for _ in range(max(1, min(20, int(count)))):
        choices = [name for name in names if not result or name != result[-1]]
        result.append(rng.choice(choices))
    VMProtectEnd()
    return result


def color_adjustments_filter(base_tag, brightness=0, contrast=0, saturation=0,
                             temperature=0, filter_name="", filter_strength=100):
    VMProtectBeginUltra(b"FCALGO:color.adjust")
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
    if filters:
        output = base_tag + "_colored"
        result = (f"[{base_tag}]" + ",".join(filters) + f"[{output}]", output)
    else:
        result = ("", base_tag)
    VMProtectEnd()
    return result


def mild_voice_filters(input_tag, duration, seed=None):
    VMProtectBeginUltra(b"FCALGO:audio.mild")
    rng = random.SystemRandom() if seed is None else random.Random(seed)
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
    filters.append(
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
    result = (filters, "dialogue")
    VMProtectEnd()
    return result


def mask_alpha(w, h, feather, margin_tb, margin_lr):
    cdef int d
    cdef double offset
    cdef list parts
    cdef str inner
    cdef str part
    cdef str result
    VMProtectBeginUltra(b"FCALGO:mask.alpha")
    d = max(1, <int>builtins.round(feather * min(w, h) / 1080.0))
    offset = d / 2.0
    parts = []
    if margin_lr > 0:
        parts.append("clip((X-W*%s+%s)/%d,0,1)" % (margin_lr, offset, d))
        parts.append("clip((W*(1-%s)-X+%s)/%d,0,1)" % (margin_lr, offset, d))
    if margin_tb > 0:
        parts.append("clip((Y-H*%s+%s)/%d,0,1)" % (margin_tb, offset, d))
        parts.append("clip((H*(1-%s)-Y+%s)/%d,0,1)" % (margin_tb, offset, d))
    if parts:
        inner = parts[0]
        for part in parts[1:]:
            inner = "min(%s,%s)" % (inner, part)
        result = "255*%s" % inner
    else:
        result = ""
    VMProtectEnd()
    return result


def butterfly_plan(double duration, double head, object hidden=None, int fps=30):
    cdef double hidden_value
    cdef double remaining
    cdef double chunk
    cdef list chunks = []

    VMProtectBeginUltra(b"FCALGO:butterfly.plan")
    try:
        hidden_value = duration + 0.0667 if hidden is None else float(hidden)
        chunks = [23.0] * <int>(hidden_value // 23.0)
        remaining = hidden_value - sum(chunks)
        if remaining > 0.02:
            chunks.append(remaining)
        return {
            "hidden": hidden_value,
            "chunks": chunks,
            "jump_frame": builtins.round((head + hidden_value) * fps),
            "main_frames": builtins.round(duration * fps),
        }
    finally:
        VMProtectEnd()


def window_matte_chain(
    int canvas_width,
    int canvas_height,
    double center_x,
    double center_y,
    double window_width,
    double window_height,
    double feather,
):
    cdef int d
    cdef double left
    cdef double top
    cdef int box_width
    cdef int box_height
    cdef int blur
    cdef str x_expr
    cdef str y_expr

    VMProtectBeginUltra(b"FCALGO:template.window")
    try:
        d = max(1, <int>builtins.round(feather * min(canvas_width, canvas_height) / 1080.0))
        left = canvas_width * (center_x - window_width / 2.0) / 100.0
        top = canvas_height * (center_y - window_height / 2.0) / 100.0
        box_width = max(1, <int>builtins.round(canvas_width * window_width / 100.0))
        box_height = max(1, <int>builtins.round(canvas_height * window_height / 100.0))
        left -= canvas_width / 2.0
        top -= canvas_height / 2.0
        x_expr = "iw/2%s%g" % ("+" if left >= 0 else "-", abs(left))
        y_expr = "ih/2%s%g" % ("+" if top >= 0 else "-", abs(top))
        blur = max(1, <int>builtins.round((d - 1) / 2.0))
        return (
            "format=gray,lutyuv=y=0,"
            "drawbox=x=%s:y=%s:w=%d:h=%d:color=white:t=fill,"
            "lutyuv=y='if(gt(val,128),255,0)',boxblur=%d:1"
        ) % (x_expr, y_expr, box_width, box_height, blur)
    finally:
        VMProtectEnd()


def concat_filter_segment(
    int index,
    double duration,
    bint has_audio,
    int width,
    int height,
    double fps,
):
    cdef str video_filter
    cdef str audio_filter

    VMProtectBeginUltra(b"FCALGO:concat.segment")
    try:
        video_filter = (
            "[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%g,"
            "format=yuv420p,trim=duration=%g,setpts=PTS-STARTPTS[v%d]"
        ) % (index, width, height, width, height, fps, duration, index)
        if has_audio:
            audio_filter = (
                "[%d:a]aresample=48000,"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                "atrim=duration=%g,asetpts=PTS-STARTPTS[a%d]"
            ) % (index, duration, index)
        else:
            audio_filter = (
                "anullsrc=r=48000:cl=stereo,"
                "atrim=duration=%g,asetpts=PTS-STARTPTS[a%d]"
            ) % (duration, index)
        return video_filter, audio_filter
    finally:
        VMProtectEnd()
