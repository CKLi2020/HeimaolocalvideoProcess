"""处理模式基类。

原版这里是瘦客户端的一半:BaseMode 只负责把界面状态整理成参数字典,
ffmpeg 命令本身由宝塔服务器按模板渲染后加密下发。
宝塔已下线,本地版把模板搬进了 mode_defs/<平台>/<通道>.json,
于是 BaseMode 多做一件事:render() 就地渲染命令。

新增通道的两种方式(对应原版「宝塔新增但客户端本地没有 mode_*.py」的通用模式):
  1. 只丢一个 mode_defs/<平台>/<通道>.json  —— 通用模式,够用
  2. 再配一个 modes/<平台>/mode_<通道>.py    —— 需要特殊参数逻辑时才写
两种都只加文件,不改 Python,重启后下拉框自动出现。
"""

import hashlib
import os

# 源视频扩展名,取自原二进制 main.py 的 VIDEO_EXTS
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".flv", ".ts", ".m4v", ".wmv")

# 模板占位符 -> build_params() 里的键。渲染时逐个 replace,
# 不用 str.format:ffmpeg 滤镜里可能出现花括号,format 会炸。
_PLACEHOLDERS = (
    "input", "aux", "output", "threads", "bitrate", "hwaccel",
    "gpu_vendor", "video_encoder", "gpu_opts", "size", "width", "height",
    "fps", "ext", "suffix", "mix_seconds", "pip_scale", "margin",
)

# 硬件编码器的质量参数。NVENC 和 AMF 的参数体系完全不同
# (nvenc 用 -preset p1..p7 / -rc vbr / -cq;amf 用 -quality / -rc cqp / -qp_i),
# 同一个 gpu_command 模板没法写死任何一边,所以由 {gpu_opts} 按厂商注入。
_GPU_OPTS = {
    "nvidia": "-preset p5 -rc vbr -cq 21 -spatial_aq 1 -temporal_aq 1",
    "amd": "-quality balanced -rc cqp -qp_i 21 -qp_p 23",
}

# 路径类占位符统一由模板自己加引号:模板里写 "{input}" / "{output}.{ext}"。
# 原版是 build_params 里就 quote() 好再交给服务器,但那样后缀只能加在引号外面
# ("路径".mp4),带空格的输出目录会被拆开。所以本地版把引号移到模板里 ——
# 这是与原版的一处刻意差异,quote() 保留给自定义模式使用。
_DEFAULT_SIZE = "720x1280"
_DEFAULT_FPS = 30


def quote(path):
    """给路径加双引号(模板替换前调用),这样带空格的路径不会被拆开。"""
    text = str(path or "")
    # Windows 路径本来就不能含双引号;真有就丢掉,免得把模板引号弄配对不上
    return '"%s"' % text.replace('"', "")


def source_stem(path):
    """产物文件名前缀。原版用源文件的 32 位 md5(实测产物
    `46edf35f6ee8d852b1d93c1a81901ddc_sph3.mp4` 就是 md5 形态)。"""
    key = os.path.normcase(os.path.abspath(str(path or "")))
    return hashlib.md5(key.encode("utf-8", "replace")).hexdigest()


def source_basename(path):
    """源文件名(去扩展名),用于 output_naming == "source" 时起名。"""
    return os.path.splitext(os.path.basename(str(path or "")))[0]


class BaseMode:
    """处理模式基类。

    类属性与原名、类型一一对应(见 work/xiaohuamao-src-recover/)。
    """

    platform = "未分组"
    id = ""
    name = "基础模式"
    needs_aux = False
    gpu_supported = False
    help_text = ""
    output_suffix = ""

    # --- 以下为本地版新增:原版这些字段由服务器下发的 json 提供 ---
    ext = "mp4"          # 原版是 json 的 ext 字段,或从命令里的 -f 推断
    size = ""            # 目标分辨率,模板里用 {size}
    fps = 0              # 目标帧率,模板里用 {fps}
    bitrate = ""         # 模式级码率覆盖,留空则用全局 default_bitrate
    command = ""         # CPU 命令模板
    gpu_command = ""     # GPU 命令模板;留空表示该模式无 GPU 方案
    desc = ""            # 原版 help/desc,界面 help 区显示

    # 混剪类模式的参数(仅 mix 通道用得上)
    mix_seconds = 6      # 每段取多长
    pip_scale = 0.35     # 画中画占主画面宽度的比例
    margin = 24          # 画中画边距(像素)

    hwaccel = ""         # 留空 = auto(让 ffmpeg 挑);可写 cuda / d3d11va / none

    # ------------------------------------------------------------------
    def has_gpu_command(self):
        """该模式是否提供了可用的 GPU 命令模板。"""
        return bool(str(self.gpu_command or "").strip())

    def input_patterns(self):
        """文件选择对话框的过滤器,与 VIDEO_EXTS 一致。"""
        return ["*" + ext for ext in VIDEO_EXTS] + ["*.*"]

    # ------------------------------------------------------------------
    def build_params(self, state, main_video=None, aux_video=None):
        """state: 程序收集的原始状态
            main_video / aux_video / output_dir / threads / use_gpu / bitrate / gpu_profile
        main_video: 当前正在处理的主视频(批量时逐个传入),None 时用 state 里的
        aux_video:  当前配对的辅视频(批量时逐个传入),None 时用 state 里的

        返回: 模板参数字典,键与 mode_defs 命令模板里的 {占位符} 对应。
        注意: output 给的是【不带后缀】的路径 —— 后缀由本模式的 ext 决定,
        原版这一步由服务器做,本地版由 render() 补。
        """
        state = state or {}
        main = main_video if main_video is not None else state.get("main_video")
        aux = aux_video if aux_video is not None else state.get("aux_video")
        use_gpu = bool(state.get("use_gpu"))

        profile = state.get("gpu_profile") or {}
        if use_gpu and profile.get("available"):
            video_encoder = profile.get("h264_encoder") or "libx264"
            gpu_vendor = profile.get("vendor") or "cpu"
            # 硬解用 auto:让 ffmpeg 自己挑可用的,挑不到就老实软解。
            # 写死 cuda 会在没装对驱动/滤镜图要回系统内存时直接报错,
            # 而加速的大头在编码器,不在解码。要强制就在 mode_defs 里写 "hwaccel"。
            hwaccel = str(getattr(self, "hwaccel", "") or "") or "auto"
            gpu_opts = _GPU_OPTS.get(gpu_vendor, _GPU_OPTS["nvidia"])
        else:
            # 原版 build_params 里 hwaccel 的兜底字面量就是 "processor"
            video_encoder = "libx264"
            gpu_vendor = "cpu"
            hwaccel = "processor"
            gpu_opts = ""

        output_dir = str(state.get("output_dir") or "output")
        threads = int(state.get("threads") or 6)
        bitrate = str(self.bitrate or state.get("bitrate") or "6000k")
        ext = str(self.ext or "mp4").lstrip(".")
        fps = int(self.fps or state.get("fps") or _DEFAULT_FPS)
        if fps <= 0:
            fps = _DEFAULT_FPS

        size = str(self.size or _DEFAULT_SIZE)
        try:
            width_text, height_text = size.lower().replace("*", "x").split("x", 1)
            width, height = int(width_text), int(height_text)
        except (ValueError, AttributeError):
            size = _DEFAULT_SIZE
            width, height = (int(v) for v in size.split("x"))

        # 产物前缀:原版是 md5(源);output_naming == "source" 时改用源文件名
        if str(state.get("output_naming") or "hash").lower() == "source":
            prefix = source_basename(main)
        else:
            prefix = source_stem(main) if main else "output"
        out_base = os.path.join(output_dir, prefix + str(self.output_suffix or ""))

        mix_seconds = int(getattr(self, "mix_seconds", 0) or 6)
        pip_scale = float(getattr(self, "pip_scale", 0) or 0.35)
        margin = int(getattr(self, "margin", 0) or 24)

        # 路径不加引号,由模板写 "{input}" / "{output}.{ext}" —— 见上方 _PLACEHOLDERS 注释
        return {
            "input": str(main or ""),
            "aux": str(aux or ""),
            "output": out_base,
            "threads": threads,
            "bitrate": bitrate,
            "hwaccel": hwaccel,
            "gpu_vendor": gpu_vendor,
            "video_encoder": video_encoder,
            "gpu_opts": gpu_opts,
            "size": "%dx%d" % (width, height),
            "width": width,
            "height": height,
            "fps": fps,
            "ext": ext,
            "suffix": str(self.output_suffix or ""),
            "mix_seconds": mix_seconds,
            "pip_scale": pip_scale,
            "margin": margin,
        }

    # ------------------------------------------------------------------
    def render(self, state, main_video=None, aux_video=None, use_gpu=None, out_base=None):
        """渲染出可直接交给 FFmpegRunner 的命令字符串。

        use_gpu: None 时取 state['use_gpu'];True 且模板无 gpu_command 时回退 command。
        out_base: 覆盖输出路径(不带后缀),worker 用临时路径时传这个。

        返回 (command, is_gpu, error)。error 非空表示渲不出来。
        """
        state = state or {}
        if use_gpu is None:
            use_gpu = bool(state.get("use_gpu"))

        template = self.gpu_command if (use_gpu and self.has_gpu_command()) else self.command
        is_gpu = bool(use_gpu and self.has_gpu_command())

        if not str(template or "").strip():
            return "", is_gpu, "模式 %s 没有配置 %s 命令模板" % (
                self.id or self.name, "GPU" if use_gpu else "CPU")

        # 把生效的 use_gpu 写回 state 再交给 build_params:
        # 否则会出现"选了 GPU 模板、参数却按 CPU 算"的错配
        # (实测表现为 GPU 模板里被塞进 CPU 的兜底值 -hwaccel processor,
        #  ffmpeg 直接 Unrecognized hwaccel)。build_params 的签名保持取证原样。
        effective = dict(state)
        effective["use_gpu"] = bool(use_gpu)
        params = self.build_params(effective, main_video, aux_video)

        if out_base is not None:
            params["output"] = str(out_base)

        command = str(template)
        for key in _PLACEHOLDERS:
            command = command.replace("{%s}" % key, str(params.get(key, "")))

        leftover = _find_placeholders(command)
        if leftover:
            return "", is_gpu, "命令模板里有未替换的占位符: %s" % (", ".join(sorted(leftover)),)

        if self.needs_aux and not (aux_video or state.get("aux_video")):
            return "", is_gpu, "该模式需要辅视频"

        return command, is_gpu, ""


def _find_placeholders(text):
    """找出 {name} 形态的残留占位符(排除 ffmpeg 常见的 {} 转义)。"""
    found = set()
    depth = 0
    start = -1
    for idx, ch in enumerate(text):
        if ch == "{":
            depth += 1
            if depth == 1:
                start = idx
        elif ch == "}":
            if depth == 1 and start >= 0:
                inner = text[start + 1:idx]
                if inner.replace("_", "").isalnum() and inner:
                    found.add(inner)
            depth = max(0, depth - 1)
    return found


__all__ = ["BaseMode", "quote", "source_stem", "source_basename", "VIDEO_EXTS"]
