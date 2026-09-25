# cython: language_level=3, binding=False, embedsignature=False
"""月落@苍狼原生算法核心。

发布构建会把本模块编译成扩展模块，再由 VMProtect Ultra 单独保护。
这里仅保留稳定、纯计算的核心步骤，文件遍历和进程调度仍由 Python 负责。
"""

from libc.math cimport round


cdef extern from "VMProtectSDK.h":
    void VMProtectBeginUltra(const char *name)
    void VMProtectEnd()


def mask_alpha(w, h, feather, margin_tb, margin_lr):
    cdef int d
    cdef double offset
    cdef list parts
    cdef str inner
    cdef str part
    cdef str result
    VMProtectBeginUltra(b"FCALGO:mask.alpha")
    d = max(1, <int>round(feather * min(w, h) / 1080.0))
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
            "jump_frame": round((head + hidden_value) * fps),
            "main_frames": round(duration * fps),
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
        d = max(1, <int>round(feather * min(canvas_width, canvas_height) / 1080.0))
        left = canvas_width * (center_x - window_width / 2.0) / 100.0
        top = canvas_height * (center_y - window_height / 2.0) / 100.0
        box_width = max(1, <int>round(canvas_width * window_width / 100.0))
        box_height = max(1, <int>round(canvas_height * window_height / 100.0))
        left -= canvas_width / 2.0
        top -= canvas_height / 2.0
        x_expr = "iw/2%s%g" % ("+" if left >= 0 else "-", abs(left))
        y_expr = "ih/2%s%g" % ("+" if top >= 0 else "-", abs(top))
        blur = max(1, <int>round((d - 1) / 2.0))
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
