# cython: language_level=3, binding=False, embedsignature=False
"""爆闪算法原生核心：帧序洗牌、滤镜图常量、iTTS/ctts 时间戳偏移重算。

发布构建把本模块编译成扩展模块，再由 VMProtect Ultra 单独保护，产物是
``app/_random_frame_swap_core.pyd``。这里只放纯计算，文件解析和进程调度仍由
Python 侧（modes/shipinhao/mode_heimao_luoyue_worker.py）负责。

明文等价实现留在 ``modes/shipinhao/heimao_luoyue_core.py``，只用于源码树调试和
对拍（见 SECURITY.md）。发布包里不放它：build_release_manifest.py 会把出现明文
等价实现当成构建错误。
"""

import random


cdef extern from "VMProtectSDK.h":
    void VMProtectBeginUltra(const char *name)
    void VMProtectEnd()


cdef extern from *:
    """
    #ifdef FC_LICENSE_GATE
    #include <windows.h>

    static int fc_host_gate_enabled(void) { return 1; }

    /* Only run inside the release launcher. Both paths come from the OS, so
       monkeypatching sys/os in Python cannot influence the answer: this
       module's own path is resolved from its code address, the running
       process image from GetModuleFileNameW(NULL). 92 is the backslash. */
    static int fc_host_ok(void) {
        static wchar_t self[32768];
        static wchar_t exe[32768];
        HMODULE module = NULL;
        DWORD n;
        wchar_t *sep;

        if (!GetModuleHandleExW(
                GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                    GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                (LPCWSTR)(const void *)&fc_host_ok, &module)) {
            return 0;
        }
        n = GetModuleFileNameW(module, self, 32767);
        if (n == 0 || n >= 32767) { return 0; }
        self[n] = 0;

        n = GetModuleFileNameW(NULL, exe, 32767);
        if (n == 0 || n >= 32767) { return 0; }
        exe[n] = 0;

        /* <release>\\app\\_random_frame_swap_core.pyd -> <release> */
        sep = wcsrchr(self, 92);
        if (sep == NULL) { return 0; }
        *sep = 0;
        sep = wcsrchr(self, 92);
        if (sep == NULL) { return 0; }
        *sep = 0;

        /* <release>\\<launcher>.exe -> <release> */
        sep = wcsrchr(exe, 92);
        if (sep == NULL) { return 0; }
        *sep = 0;

        return _wcsicmp(self, exe) == 0;
    }
    /* Deny: end the process outright, never touching Python.

       0x46434731 is "FCG1" -- the same code flowcut_core uses, so the exit
       status alone tells the user "the host gate refused", whichever core was
       called first. See native_src/flowcut_core.pyx for why the refusal is a
       bare ExitProcess instead of a Python exception (VMProtect Ultra does not
       survive exception paths once its regions are virtualized). This module
       does not need to mark the gate itself: it has only 3 markers, and the
       refusal never unwinds into Python. */
    static void fc_host_deny(void) {
        ExitProcess(0x46434731u);
    }
    #else
    static int fc_host_gate_enabled(void) { return 0; }
    static int fc_host_ok(void) { return 1; }
    static void fc_host_deny(void) { }
    #endif
    """
    int fc_host_gate_enabled()
    int fc_host_ok()
    void fc_host_deny()


# ── 算法宿主机门禁 ──────────────────────────────────────────────────────
# 和 flowcut_core 同一套判定：发布构建（gcc 加 -DFC_LICENSE_GATE）时，每个算法
# 入口先确认自己确实运行在发布启动器进程里——宿主可执行文件必须与本扩展模块处于
# 同一个发布根目录（<发布根>\app\_random_frame_swap_core.pyd 对 <发布根>\<启动器>.exe）。
# 拿系统里任意 CPython 3.9 旁加载本模块、或把它嵌进别人的程序，都在这里被拒。
# 未定义该宏时一切放行，源码调试与对拍完全不受影响。
#
# 2026-10-05 实测：本模块导出的三个函数与 modes/shipinhao/heimao_luoyue_core.py
# 的明文实现在 42 组 shuffled_order、8 组 special_offsets 和 filter_graph 上逐位
# 相等，所以换成受保护实现不会改变爆闪频道的出片结果。


cdef void _ensure_host():
    """每个算法入口的第一道闸：不在发布启动器进程内就直接终止进程。"""
    if fc_host_gate_enabled() == 0:
        return
    if fc_host_ok() == 0:
        fc_host_deny()


_FILTER_GRAPH = (
    "[0:v:0]fps=30,scale=720:1280:flags=lanczos,setsar=1,"
    "settb=1/60,setpts=2*N[va];"
    "[1:v:0]fps=30,scale=720:1280:force_original_aspect_ratio=increase:"
    "flags=lanczos,crop=720:1280,setsar=1,settb=1/60,setpts=2*N+1[vb];"
    "[va][vb]interleave=nb_inputs=2,settb=1/60,setpts=N[vout]"
)


def filter_graph():
    """爆闪拼接用的 ffmpeg 滤镜图：两路 720x1280 交织成 60fps 输出。"""
    _ensure_host()
    VMProtectBeginUltra(b"RFCORE:graph")
    result = _FILTER_GRAPH
    VMProtectEnd()
    return result


def shuffled_order(count, seed=None):
    """把 0..count-1 洗成播放顺序。seed 为 None 时用系统熵，每次不同。"""
    _ensure_host()
    VMProtectBeginUltra(b"RFCORE:shuffle")
    order = list(range(count))
    (random.SystemRandom() if seed is None else random.Random(seed)).shuffle(order)
    VMProtectEnd()
    return order


def special_offsets(durations, offsets):
    """重算 ctts 偏移：按解码时间累积，再抵消每个采样 512 的时间戳基准差。"""
    _ensure_host()
    VMProtectBeginUltra(b"RFCORE:offsets")
    old_dts, result = 0, []
    for index, (duration, offset) in enumerate(zip(durations, offsets)):
        result.append(old_dts + offset - index * 512)
        old_dts += duration
    VMProtectEnd()
    return result
