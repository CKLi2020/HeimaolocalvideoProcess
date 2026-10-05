# cython: language_level=3, binding=False, embedsignature=False
"""月落@苍狼原生算法核心。

发布构建会把本模块编译成扩展模块，再由 VMProtect Ultra 单独保护。
这里仅保留稳定、纯计算的核心步骤，文件遍历和进程调度仍由 Python 负责。
"""

import builtins
import math
import random
from datetime import datetime, timedelta, timezone


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


def _qilin_partition(total, count, rng):
    minimum = 8
    while True:
        cuts = sorted(rng.sample(range(minimum, total - minimum), count - 1))
        points = [0, *cuts, total]
        if all(right - left >= minimum for left, right in zip(points, points[1:])):
            return list(zip(points, points[1:]))


def _qilin_random_color(rng):
    return "0x%02x%02x%02x" % tuple(rng.randint(30, 250) for _ in range(3))


def _qilin_mosaic_source(columns, rows, rng):
    width, height = 198, 188
    filters = ["color=c=black:s=%dx%d:r=1" % (width, height), "format=rgb24"]
    vertical_cells = _qilin_partition(height, rows, rng)
    for left, right in _qilin_partition(width, columns, rng):
        for top, bottom in vertical_cells:
            filters.append(
                "drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=fill"
                % (left, top, right - left, bottom - top, _qilin_random_color(rng))
            )
    return ",".join(filters)


def _qilin_grid_graph(rng):
    lines = [
        "[0:v]split=9[a_0][a_1][a_2][a_3][a_4][a_5][a_6][a_7][a_8];",
        "[1:v]split=8[g_0][g_1][g_2][g_3][g_4][g_5][g_6][g_7];",
        (
            "[2:v]fps=30,scale=198:188:flags=lanczos,setsar=1,format=yuv420p,"
            "rotate='%.3f*t':ow=198:oh=188:c=black,crop=190:180:4:4,"
            "setsar=1,format=yuv420p,split=3[r0][r1][r2];"
        )
        % rng.uniform(0.2, 0.3),
    ]
    for index in range(17):
        source = "a" if index < 9 else "g"
        source_index = index if index < 9 else index - 9
        saturation = rng.uniform(0.9, 1.15)
        lines.append(
            (
                "[%s_%d]fps=30,scale=198:188:flags=lanczos,setsar=1,format=yuv420p,"
                "hue=h='%.6f*t+%.3f':s=%.3f,"
                "eq=brightness=%.3f:contrast=%.3f:saturation=%.3f,"
                "rotate='%.3f*sin(2*PI*%.3f*t)':ow=198:oh=188:c=black,"
                "crop=190:180:4:4,setsar=1,format=yuv420p[c%d];"
            )
            % (
                source, source_index, rng.uniform(25, 55), rng.uniform(0, 360),
                saturation, rng.uniform(-0.01, 0.04), rng.uniform(0.95, 1.06),
                saturation, rng.uniform(0.03, 0.06), rng.uniform(0.3, 1.0), index,
            )
        )
    inputs = "".join("[c%d]" % index for index in range(17)) + "[r0][r1][r2]"
    layout = "|".join(
        "%d_%d" % (column * 190, row * 180)
        for row in range(4) for column in range(5)
    )
    lines.append(
        "%sxstack=inputs=20:layout=%s,gblur=sigma=%.3f,"
        "setsar=1,format=yuv420p[grid]"
        % (inputs, layout, rng.uniform(0.8, 1.0))
    )
    return "\n".join(lines)


def _qilin_blend_graph(width, height, rng):
    tempo = rng.uniform(1.004, 1.006)
    return (
        "[0:v]fps=30,scale=%d:%d:flags=lanczos,setsar=1,"
        "format=yuv420p,setpts=PTS/%.4f[main];"
        "[1:v]fps=30,scale=%d:%d:flags=lanczos,setsar=1,"
        "format=yuv420p[grid];"
        "[main][grid]blend=all_expr='if(lt(N\\,3)\\,A\\,"
        "if(eq(mod(Y\\,2)\\,0)\\,A\\,B))':shortest=1,"
        "setfield=tff,format=yuv420p[vout];"
        "anoisesrc=color=pink:amplitude=%.6f:sample_rate=44100,"
        "aformat=channel_layouts=stereo[bg_noise];"
        "[0:a]aresample=44100,aformat=channel_layouts=stereo,"
        "atempo=%.4f,vibrato=f=%.3f:d=%.3f,volume=%.3f[a_mod];"
        "[a_mod][bg_noise]amix=inputs=2:duration=first,"
        "aformat=channel_layouts=stereo,alimiter=limit=-0.5dB,"
        "asetpts=PTS-STARTPTS[aout]"
    ) % (
        width, height, tempo, width, height, rng.uniform(0.0008, 0.001),
        tempo, rng.uniform(0.3, 0.4), rng.uniform(0.04, 0.05),
        rng.uniform(1.05, 1.1),
    )


def qilin_pipeline_plan(int width, int height, seed=None):
    cdef object rng
    cdef object creation_time
    cdef double frame_seek
    cdef str keyframes

    VMProtectBeginUltra(b"FCALGO:qilin.1004.pipeline")
    try:
        rng = random.SystemRandom() if seed is None else random.Random(seed)
        grid_graph = _qilin_grid_graph(rng)
        blend_graph = _qilin_blend_graph(width, height, rng)
        frame_seek = rng.uniform(0.5, 2.0)
        keyframes = "0,%.3f,%.3f" % (rng.uniform(5.5, 6.0), rng.uniform(6.6, 7.0))
        creation_time = datetime.now(timezone.utc) - timedelta(
            days=rng.randint(7, 24), seconds=rng.randint(0, 86399)
        )
        return {
            "grid_graph": grid_graph,
            "blend_graph": blend_graph,
            "frame_seek": "%.2f" % frame_seek,
            "keyframes": keyframes,
            "creation_time": creation_time.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            "geo_source": _qilin_mosaic_source(6, 6, rng),
            "rotation_source": _qilin_mosaic_source(4, 6, rng),
        }
    finally:
        VMProtectEnd()


def qilin_sps_compat_byte(tail):
    cdef bytes raw
    cdef str significant
    cdef object vui_tails
    cdef int before
    cdef int stop

    VMProtectBeginUltra(b"FCALGO:qilin.1004.sps")
    try:
        raw = bytes(tail)
        if len(raw) != 8:
            raise ValueError("Qilin SPS tail must contain exactly 8 bytes")
        significant = "".join("%08d" % int(bin(byte)[2:]) for byte in raw).rstrip("0")
        vui_tails = tuple(
            "110101" + ("%08d" % int(bin(primaries)[2:])) +
            ("%08d" % int(bin(transfer)[2:])) + "00000001" + "00000000"
            for primaries in (1, 2)
            for transfer in (1, 2)
        )
        before = raw[-1]
        if before == 0:
            raise ValueError("Qilin SPS has an unexpected zero terminal byte")
        if any(significant.endswith(vui + "01") for vui in vui_tails):
            return before
        if not any(significant.endswith(vui + "1") for vui in vui_tails):
            raise ValueError("SPS VUI tail does not match the validated Qilin layout")
        stop = before & -before
        if stop <= 1:
            raise ValueError("SPS has no alignment space for Qilin compatibility")
        return (before & ~stop) | (stop >> 1)
    finally:
        VMProtectEnd()


_LIUYING_BASE_FILTER = (
    "fps=60,scale=576:1248:force_original_aspect_ratio=decrease,"
    "pad=576:1248:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
)
_LIUYING_SEED_STEP = 104729
_LIUYING_RANDOM_INPUTS = "random(0);" * 8
_LIUYING_FLASH_ENABLE = "gte(mod(in,60),10)*lte(mod(in,60),50)*eq(mod(in,10),0)"
_LIUYING_FLASH_INDEX = "ceil(in/12)"


def _liuying_perspective(seed, enabled_expr=None, random_frame_index="in", subtle=False):
    if subtle:
        geometry = (
            "st(1,0.49+0.02*random(0));"
            "st(2,0.49+0.02*random(0));"
            "st(3,1);"
            "st(4,0);"
            "st(5,(PI/180)*(1+4*random(0)));"
        )
    else:
        geometry = (
            "st(1,0.5+0.3*random(0));"
            "st(2,0.5+0.3*random(0));"
            "st(3,if(lt(random(0),0.5),-1,1));"
            "st(4,lt(random(0),0.5));"
            "st(5,(PI/4+PI/4*random(0))*ld(4));"
        )
    state = (
        f"st(0,{int(seed)}+({random_frame_index})*{_LIUYING_SEED_STEP});"
        f"{_LIUYING_RANDOM_INPUTS}{geometry}"
        "st(6,cos(ld(5)));"
        "st(7,sin(ld(5)));"
        "st(8,min("
        "max(0.5,W*ld(1)-2)/(abs(ld(6))*(W-1)+abs(ld(7))*(H-1)),"
        "max(0.5,H*ld(2)-2)/(abs(ld(7))*(W-1)+abs(ld(6))*(H-1))"
        "));"
    )
    if enabled_expr:
        state += f"st(9,{enabled_expr});"
    corners = {
        "x0": "(W-1)/2+ld(3)*ld(8)*(ld(6)*(0-(W-1)/2)+ld(7)*(0-(H-1)/2))",
        "y0": "(H-1)/2+ld(8)*(-ld(7)*(0-(W-1)/2)+ld(6)*(0-(H-1)/2))",
        "x1": "(W-1)/2+ld(3)*ld(8)*(ld(6)*(W-(W-1)/2)+ld(7)*(0-(H-1)/2))",
        "y1": "(H-1)/2+ld(8)*(-ld(7)*(W-(W-1)/2)+ld(6)*(0-(H-1)/2))",
        "x2": "(W-1)/2+ld(3)*ld(8)*(ld(6)*(0-(W-1)/2)+ld(7)*(H-(H-1)/2))",
        "y2": "(H-1)/2+ld(8)*(-ld(7)*(0-(W-1)/2)+ld(6)*(H-(H-1)/2))",
        "x3": "(W-1)/2+ld(3)*ld(8)*(ld(6)*(W-(W-1)/2)+ld(7)*(H-(H-1)/2))",
        "y3": "(H-1)/2+ld(8)*(-ld(7)*(W-(W-1)/2)+ld(6)*(H-(H-1)/2))",
    }
    if enabled_expr:
        identities = {
            "x0": "0", "y0": "0", "x1": "W", "y1": "0",
            "x2": "0", "y2": "H", "x3": "W", "y3": "H",
        }
        corners = {
            name: f"if(ld(9),{value},{identities[name]})"
            for name, value in corners.items()
        }
    coordinates = ":".join(f"{name}='{state}{value}'" for name, value in corners.items())
    return f"perspective={coordinates}:sense=source:interpolation=linear:eval=frame"



def liuying_video_filter(seed, random_enhance=False):
    cdef str result
    VMProtectBeginUltra(b"FCALGO:liuying.1003.video")
    try:
        result = _LIUYING_BASE_FILTER + "," + _liuying_perspective(
            seed, _LIUYING_FLASH_ENABLE, _LIUYING_FLASH_INDEX
        )
        if random_enhance:
            result += "," + _liuying_perspective(
                int(seed) + _LIUYING_SEED_STEP,
                _LIUYING_FLASH_ENABLE,
                _LIUYING_FLASH_INDEX,
                True,
            )
        return result
    finally:
        VMProtectEnd()


def liuying_perspective_filter(seed):
    VMProtectBeginUltra(b"FCALGO:liuying.1003.branch")
    try:
        return _liuying_perspective(seed)
    finally:
        VMProtectEnd()


def liuying_flash_filter(seed):
    VMProtectBeginUltra(b"FCALGO:liuying.1003.flash")
    try:
        return _liuying_perspective(seed, _LIUYING_FLASH_ENABLE, _LIUYING_FLASH_INDEX)
    finally:
        VMProtectEnd()


def liuying_base_filter():
    VMProtectBeginUltra(b"FCALGO:liuying.1003.base")
    try:
        return _LIUYING_BASE_FILTER
    finally:
        VMProtectEnd()


def liuying_seed(base_seed, task_index):
    VMProtectBeginUltra(b"FCALGO:liuying.1003.seed")
    try:
        return int(base_seed) + int(task_index) * _LIUYING_SEED_STEP
    finally:
        VMProtectEnd()


def motianxinglun_pipeline_plan(duration):
    VMProtectBeginUltra(b"FCALGO:motianxinglun.1005.pipeline")
    try:
        return {
            "duration": "%.3f" % max(0.001, float(duration)),
            "image_size": "720x1280",
            "image_fps": "120",
        }
    finally:
        VMProtectEnd()


def tianbaixinglun_pipeline_plan(duration):
    VMProtectBeginUltra(b"FCALGO:tianbaixinglun.1005.pipeline")
    try:
        return {
            "duration": "%.3f" % max(0.001, float(duration)),
            "main_filter": (
                "scale=720:1280:force_original_aspect_ratio=disable,"
                "setsar=1:1,fps=60"
            ),
            "geometry_filter": (
                "scale=848:1510:flags=lanczos,"
                "zoompan=z='1.04+0.055*sin(on/17)*sin(on/17)':"
                "x='iw/2-(iw/zoom/2)+18*sin(on/5)':"
                "y='ih/2-(ih/zoom/2)+32*cos(on/7)':d=1:s=720x1280:fps=60,"
                "rotate='0.11*sin(2*PI*t/2.8)+0.028*t':ow=720:oh=1280:c=black,"
                "hue=h='18*t',setsar=1:1,format=yuv420p"
            ),
            "blend_filter": (
                "[0:v]scale=720:1280,setsar=1,fps=60,setpts=PTS-STARTPTS,"
                "format=yuv420p[main];"
                "[1:v]scale=720:1280,setsar=1,fps=60,setpts=PTS-STARTPTS,"
                "format=yuv420p[geo];"
                "[main][geo]blend=all_mode=screen:all_opacity=0.070:shortest=1,"
                "format=yuv420p[v]"
            ),
        }
    finally:
        VMProtectEnd()


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
