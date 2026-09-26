"""本机 GPU 与 ffmpeg 硬件编码器识别。

函数名、探测顺序、正则、提示语均照反编译取证恢复。
"""

import os
import re
import shutil
import subprocess

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# 记忆化:一次进程内 -encoders 与自检各只跑一次,探测可能要几百毫秒
_ENCODER_CACHE = {}
_ENCODER_TEST_CACHE = {}

# 厂商 -> (h264 编码器, hevc 编码器, 显示名)
_VENDOR = {
    "nvidia": ("h264_nvenc", "hevc_nvenc", "N卡"),
    "amd": ("h264_amf", "hevc_amf", "A卡"),
}

_ENCODER_RE = re.compile(r"\b([a-z0-9_]+_(?:nvenc|amf|qsv))\b")


def _startupinfo():
    """Windows 上隐藏子进程控制台窗口。"""
    if os.name != "nt":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def _run(args, timeout=20):
    """跑一条外部命令,吞掉所有异常,返回 stdout 文本(失败返回 "")。"""
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            startupinfo=_startupinfo(),
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    try:
        return proc.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def _classify_gpu(name):
    """把显卡名归到 nvidia / amd,认不出或不是真显卡返回 None。"""
    low = (name or "").lower()
    if not low:
        return None
    # 这两类是虚拟/兜底显示适配器,不能当显卡用
    if "microsoft basic" in low or "remote display" in low:
        return None
    if any(k in low for k in ("nvidia", "geforce", "quadro", "tesla")):
        return "nvidia"
    if any(k in low for k in ("amd", "radeon", "advanced micro devices")):
        return "amd"
    if re.search(r"\bati\b", low):
        return "amd"
    return None


def _detect_controller_names():
    """枚举系统显示适配器名称,失败返回 []。"""
    names = []

    out = _run([
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }",
    ])
    if out:
        names = [line.strip() for line in out.splitlines() if line.strip()]

    if not names:
        out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
        if out:
            names = [line.strip() for line in out.splitlines() if line.strip()]

    if not names:
        out = _run(["wmic", "path", "win32_VideoController", "get", "Name"])
        if out:
            lines = [line.strip() for line in out.splitlines()]
            # wmic 输出首行是列名 "Name",末行常为空
            names = [ln for ln in lines[1:] if ln and ln.lower() != "name"]

    unique_names, seen = [], set()
    for name in names:
        low = name.lower()
        if "microsoft basic" in low or "remote display" in low:
            continue
        key = low
        if key in seen:
            continue
        seen.add(key)
        unique_names.append(name)
    return unique_names


def detect_gpu_names():
    """返回系统检测到的显卡型号,包括 Intel 等暂不支持硬件编码的显卡。"""
    return _detect_controller_names()


def _classify_gpus(names):
    gpus, seen = [], set()
    for name in names:
        vendor = _classify_gpu(name)
        if not vendor:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        gpus.append({"name": name, "vendor": vendor})
    return gpus


def detect_gpus():
    """枚举本机可用于本程序硬件编码的显卡,失败返回 []。"""
    return _classify_gpus(_detect_controller_names())


def available_encoders(ffmpeg_path):
    """读 `ffmpeg -encoders`,返回本机可用的 *_nvenc/_amf/_qsv 编码器名集合。

    失败(没 ffmpeg / 跑不起来 / 超时)返回空集合,由调用方当作"无硬件编码器"处理。
    """
    key = str(ffmpeg_path or "")
    if key in _ENCODER_CACHE:
        return _ENCODER_CACHE[key]

    result = set()
    if key and os.path.exists(key):
        out = _run([key, "-hide_banner", "-encoders"], timeout=30)
        if out:
            result = set(_ENCODER_RE.findall(out))

    _ENCODER_CACHE[key] = result
    return result


def encoder_self_test(ffmpeg_path, encoder):
    """真跑一帧,确认这个硬件编码器在本机能用(驱动/显卡/编码器三者都对得上)。

    装了 ffmpeg 不代表 h264_nvenc 真能跑:老驱动、无显卡、独显被禁用都会在这里露馅。
    命令取自原二进制 core/hardware.py。
    """
    key = (str(ffmpeg_path or ""), str(encoder or ""))
    if key in _ENCODER_TEST_CACHE:
        return _ENCODER_TEST_CACHE[key]

    ok = False
    if key[0] and key[1] and os.path.exists(key[0]):
        args = [
            key[0], "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=256x256:rate=10",
            "-frames:v", "1", "-an",
            "-c:v", key[1], "-pix_fmt", "yuv420p",
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                timeout=30,
                startupinfo=_startupinfo(),
                creationflags=_CREATE_NO_WINDOW,
            )
            ok = proc.returncode == 0
        except Exception:
            ok = False

    _ENCODER_TEST_CACHE[key] = ok
    return ok


def detect_gpu_profile(ffmpeg_path=None):
    """自动选择 GPU 编码方案。优先 N 卡(nvenc),其次 A 卡(amf)。

    没有可用编码器时 available=False,并把原因写进 reason/warning 供界面展示。
    返回 dict: available / vendor / vendor_label / h264_encoder / hevc_encoder /
              encoders_checked / warning / reason
    """
    profile = {
        "available": False,
        "vendor": None,
        "vendor_label": "",
        "h264_encoder": "",
        "hevc_encoder": "",
        "encoders_checked": set(),
        "gpu_names": [],
        "warning": "",
        "reason": "",
    }

    gpu_names = _detect_controller_names()
    profile["gpu_names"] = gpu_names
    gpus = _classify_gpus(gpu_names)
    if not gpus:
        profile["reason"] = "未识别"
        profile["warning"] = "未检测到 N卡/A卡"
        return profile

    encoders = available_encoders(ffmpeg_path)
    profile["encoders_checked"] = encoders

    # N 卡优先,其次 A 卡
    gpus.sort(key=lambda g: 0 if g["vendor"] == "nvidia" else 1)
    first_reason = ""

    for gpu in gpus:
        vendor = gpu["vendor"]
        h264, hevc, label = _VENDOR[vendor]

        if h264 not in encoders or hevc not in encoders:
            # ffmpeg 里没编进这个硬件编码器
            first_reason = first_reason or "ffmpeg 未启用对应硬件编码器"
            continue

        if not encoder_self_test(ffmpeg_path, h264) or not encoder_self_test(ffmpeg_path, hevc):
            first_reason = first_reason or "硬件编码器自检未通过"
            continue

        profile.update({
            "available": True,
            "vendor": vendor,
            "vendor_label": label,
            "h264_encoder": h264,
            "hevc_encoder": hevc,
        })
        return profile

    profile["reason"] = first_reason or "未找到可用硬件编码器"
    profile["warning"] = profile["reason"]
    return profile


def gpu_summary(profile):
    """给侧边栏用的一行本机信息。"""
    profile = profile or {}
    names = profile.get("gpu_names") or []
    if names:
        name_text = ", ".join(names)
        if profile.get("available"):
            return "%s (%s，可用于硬件编码)" % (
                name_text, profile.get("vendor_label") or "GPU")
        return "%s (已检测到，硬件编码不可用)" % name_text
    if not profile.get("available"):
        return "未检测到 GPU"
    return "%s (可用于硬件编码)" % (profile.get("vendor_label") or "GPU")


__all__ = [
    "detect_gpus", "detect_gpu_names", "detect_gpu_profile", "available_encoders",
    "encoder_self_test", "gpu_summary", "_classify_gpu",
]
