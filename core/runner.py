"""ffmpeg / ffprobe 执行器。

- ffmpeg.exe / ffprobe.exe 放在 bin/ 目录(随程序分发)。
- argv 直启(不过 cmd shell):
    1. 中文 drawtext 等滤镜参数不会被 GBK 编码搅乱
    2. Windows 的 CreateProcess 用父进程 PATH 找程序,裸名字 "ffmpeg" 会 WinError 2,
       所以启动前把命令首词解析成本地 bin 的完整路径
- 支持进度回调、日志回调、强制停止(Windows 整树强杀)
- last_stderr 仅内存保留最近的 ffmpeg 输出(上限 300 行),默认不落盘

本地版相对原版的改动:
- 去掉命令隐藏(_hide_args 写 NTFS ADS + 覆写子进程命令行)与抓包工具拦截
  (原由 core.guard 提供,一发现 Wireshark/Fiddler 就拒绝处理)。
  本地版日志直接显示明文命令,排障方便。
- 去掉了原版的 _apply_encoder_profile(GPU<->CPU 选项改写)。
  原版那条路只做 CPU 清理,因为 GPU 命令由服务器模板生成;
  本地版 GPU/CPU 是 mode_defs 里的两份独立模板(command / gpu_command),
  GPU 失败时重新渲染 CPU 模板即可 —— 这也正是原版日志
  「GPU处理失败，重新获取CPU原命令重试」描述的行为,比改 argv 干净。
- 新增 verify_output():收尾断言产物流结构正常；默认 1 视频 + 最多 1 音频，
  已取证的特殊通道可声明精确音轨数。
  这是本地重写自身的完整性保障；此前据 output/ 样片推断原版会生成多轨坏文件，
  后续已证实样片来自另一个本地脚本，与原版无关。
"""

import json
import os
import re
import shlex
import subprocess
import threading

from .build_config import BASE_DIR, CLIENT_DIR

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_CREATE_NEW_PROCESS_GROUP = 0x00000200 if os.name == "nt" else 0

MAX_STDERR_LINES = 300

# 进度解析。三条正则取自原二进制 core/runner.py。
_PROGRESS_TIME_RE = re.compile(r"^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)$")
_PROGRESS_US_RE = re.compile(r"^out_time_(?:us|ms)=(\d+)$")
_TIME_RE = re.compile(r"time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)")

# `-progress pipe:2` 吐的键;这些行不进日志,否则一秒钟好几行会把日志冲掉
_PROGRESS_KEYS = frozenset((
    "frame", "fps", "stream_0_0_q", "bitrate", "total_size", "out_time_us",
    "out_time_ms", "out_time", "dup_frames", "drop_frames", "speed", "progress",
))

# 编码器集合,取自原二进制 core/runner.py,用于判断模板里的编码器是不是硬件编码器
_H264_CODECS = {"libx264", "h264_nvenc", "h264_amf", "h264_qsv"}
_H265_CODECS = {"libx265", "hevc_nvenc", "hevc_amf", "hevc_qsv"}
HARDWARE_CODECS = _H264_CODECS | _H265_CODECS


def _hide_child_windows():
    if os.name != "nt":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


# --------------------------------------------------------------------------
# 可执行文件查找
# --------------------------------------------------------------------------

def _resolve(cfg_path, exe_name):
    """查找可执行文件,优先级:

    1. config.json 里配的路径(绝对路径,或相对 rebuild/、相对 client/ 的路径)
    2. rebuild/bin/ 与 client/bin/
    3. 原程序目录的 bin/(复用原有 ffmpeg,不必复制 200MB)
    4. 系统 PATH
    """
    import shutil

    suffix = ".exe" if os.name == "nt" else ""
    raw = str(cfg_path or "").strip()

    cands = []
    if raw:
        if os.path.isabs(raw):
            cands.append(raw)
        else:
            cands.append(os.path.join(BASE_DIR, raw))
            cands.append(os.path.join(CLIENT_DIR, raw))

    for base in (BASE_DIR, CLIENT_DIR, os.path.dirname(BASE_DIR)):
        cands.append(os.path.join(base, exe_name + suffix))
        cands.append(os.path.join(base, "bin", exe_name + suffix))
        if raw:
            cands.append(os.path.join(base, os.path.basename(raw)))

    for cand in cands:
        if cand and os.path.isfile(cand):
            return os.path.normpath(cand)

    found = shutil.which(exe_name)
    return os.path.normpath(found) if found else ""


def find_ffmpeg(cfg):
    """定位 ffmpeg.exe。"""
    return _resolve((cfg or {}).get("ffmpeg_path"), "ffmpeg")


def find_ffprobe(cfg):
    """定位 ffprobe.exe。"""
    return _resolve((cfg or {}).get("ffprobe_path"), "ffprobe")


# --------------------------------------------------------------------------
# ffprobe
# --------------------------------------------------------------------------

def probe_media(cfg, media_path, timeout=60):
    """跑一次 ffprobe,返回解析后的 JSON dict;失败返回 None。"""
    exe = find_ffprobe(cfg)
    if not exe or not media_path or not os.path.isfile(media_path):
        return None
    args = [exe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", media_path]
    try:
        proc = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, timeout=timeout,
            startupinfo=_hide_child_windows(), creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return None


def probe_duration(cfg, media_path):
    """用 ffprobe 获取媒体时长(秒),失败返回 None。"""
    info = probe_media(cfg, media_path)
    if not info:
        return None
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


def verify_output(cfg, media_path, expected_audio_tracks=None):
    """收尾校验:一条视频轨、音轨数符合通道声明、时长为正。

    这是本地重写自身的完整性保障，不代表原版曾生成过多轨坏文件。
    返回 (ok: bool, message: str)。ok=False 时调用方应删掉产物并记为失败 ——
    宁可少一个产物,也不要交付一个播不动的文件。
    """
    if not media_path or not os.path.isfile(media_path):
        return False, "产物不存在"
    if os.path.getsize(media_path) <= 0:
        return False, "产物是空文件"

    info = probe_media(cfg, media_path)
    if info is None:
        return False, "ffprobe 读不出产物(文件损坏或不是有效媒体)"

    streams = info.get("streams")
    if not isinstance(streams, list):
        return False, "ffprobe 返回结构异常"

    videos = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audios = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]

    if len(videos) != 1:
        return False, "视频轨数量异常: %d 条(应为 1 条)" % len(videos)
    if expected_audio_tracks is None and len(audios) > 1:
        return False, "音频轨数量异常: %d 条(应不超过 1 条)" % len(audios)
    if expected_audio_tracks is not None and len(audios) != int(expected_audio_tracks):
        return False, "音频轨数量异常: %d 条(应为 %d 条)" % (
            len(audios), int(expected_audio_tracks))

    raw_duration = (info.get("format") or {}).get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        duration = None
    if duration is None or duration <= 0:
        return False, "时长字段异常: %s" % (raw_duration,)

    return True, "%.2fs %dx%d" % (
        duration,
        int(videos[0].get("width") or 0),
        int(videos[0].get("height") or 0),
    )


# --------------------------------------------------------------------------
# 命令 -> argv
# --------------------------------------------------------------------------

def _cmd_to_argv(command):
    """把 shell 命令字符串拆成 argv 数组:
    - 去掉 Shell 层的双引号(路径等)。
    - 保留 ffmpeg 滤镜语法的单引号(drawtext text='龙' 等)。
    拆不开(引号不配对等)返回 None,调用方回退 shell 方式。
    """
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        return None
    if not parts:
        return None

    argv = []
    for token in parts:
        # posix=False 会把引号原样留下;这里只剥外层双引号,单引号必须原样交给 ffmpeg
        if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
            token = token[1:-1]
        argv.append(token)
    return argv


def _opt_name(token):
    """取选项名(忽略前导连字符与 :stream 后缀);不是选项返回 None。

    `-c:v` -> "c"   `--foo=bar` -> "foo"   `-y` -> "y"   `/path` -> None
    """
    if not token or not token.startswith("-") or token == "-":
        return None
    body = token.lstrip("-")
    if not body:
        return None
    body = body.split("=", 1)[0]
    return body.split(":", 1)[0]


def _has_opt(argv, opt_name):
    """argv 里有没有这个选项。"""
    return any(_opt_name(token) == opt_name for token in argv)


def _is_ffmpeg_argv(arg):
    """命令首词是不是 ffmpeg(用来判断要不要注入进度参数)。"""
    if not arg:
        return False
    return os.path.splitext(os.path.basename(arg.strip('"')))[0].lower() == "ffmpeg"


def _inject_progress_args(argv):
    """让 ffmpeg 输出可解析进度;只读进度字段,不显示到日志。

    插在输出文件之前而不是追加到末尾:ffmpeg 全局选项位置虽然宽松,
    但放在输出 URL 之后容易被当成输出选项,插在末位之前最稳。
    """
    if not argv or not _is_ffmpeg_argv(argv[0]):
        return argv
    if _has_opt(argv, "progress"):
        return argv
    extra = ["-progress", "pipe:2", "-stats_period", "0.5"]
    if len(argv) >= 2:
        return argv[:-1] + extra + [argv[-1]]
    return argv + extra


def _seconds_from_progress_line(line):
    """从 ffmpeg 的一行输出里取秒数;取不到返回 None。"""
    if not line:
        return None
    text = line.strip()
    match = _PROGRESS_TIME_RE.match(text)
    if match:
        return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    match = _PROGRESS_US_RE.match(text)
    if match:
        return int(match.group(1)) / 1e6
    match = _TIME_RE.search(text)
    if match:
        return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    return None


def _is_progress_line(line):
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    return key in _PROGRESS_KEYS


# --------------------------------------------------------------------------
# 执行器
# --------------------------------------------------------------------------

class FFmpegRunner:
    """ffmpeg 执行器:启动 / 停止 / 进度回调 / 日志回调。"""

    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.proc = None
        self.last_stderr = []
        self._lock = threading.Lock()
        self._stop_requested = False

    @property
    def is_running(self):
        proc = self.proc
        return proc is not None and proc.poll() is None

    def _resolve_exe(self, name):
        """把命令首词(ffmpeg/ffprobe 等裸名字)解析成完整可执行路径。"""
        if not name:
            return name
        stem = os.path.splitext(os.path.basename(name))[0].lower()
        if stem not in ("ffmpeg", "ffprobe"):
            return name
        cfg_key = "ffmpeg_path" if stem == "ffmpeg" else "ffprobe_path"
        return _resolve(self.cfg.get(cfg_key), stem) or name

    def stop(self):
        """强制停止(Windows 整树强杀)。"""
        self._stop_requested = True
        with self._lock:
            proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=15, startupinfo=_hide_child_windows(),
                    creationflags=_CREATE_NO_WINDOW,
                )
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass

    def run(self, command, duration=None, on_log=None, on_progress=None):
        """跑一条 ffmpeg 命令。

        command:     完整命令字符串(模板渲染后的结果)
        duration:    源时长(秒),给了才算百分比;None 则只回调 None 进度
        on_log:      def (line: str)
        on_progress: def (percent: float)

        返回 ffmpeg 退出码;启动失败返回 -1;被停止返回 -2。
        """
        def emit_log(text):
            if on_log:
                try:
                    on_log(text)
                except Exception:
                    pass

        argv = _cmd_to_argv(command)
        use_shell = argv is None
        if use_shell:
            # 引号不配对,拆不开;只能交给 shell(中文参数可能有编码风险)
            argv = command
        else:
            argv = list(argv)
            argv[0] = self._resolve_exe(argv[0])
            argv = _inject_progress_args(argv)

        self.last_stderr = []
        self._stop_requested = False

        emit_log("$ " + (command if use_shell else subprocess.list2cmdline(argv)))

        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,     # 进度走 pipe:2,和 stderr 一起读
                stdin=subprocess.DEVNULL,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                shell=use_shell,
                startupinfo=_hide_child_windows(),
                creationflags=_CREATE_NEW_PROCESS_GROUP,
            )
        except Exception as exc:
            emit_log("启动 ffmpeg 失败: %s: %s" % (type(exc).__name__, exc))
            return -1

        with self._lock:
            self.proc = proc

        last_pct = None
        try:
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                if not _is_progress_line(line):
                    emit_log(line)
                self.last_stderr.append(line)
                if len(self.last_stderr) > MAX_STDERR_LINES:
                    del self.last_stderr[:len(self.last_stderr) - MAX_STDERR_LINES]

                if on_progress and duration and duration > 0:
                    seconds = _seconds_from_progress_line(line)
                    if seconds is not None:
                        pct = max(0.0, min(100.0, seconds * 100.0 / duration))
                        if last_pct is None or pct > last_pct:
                            last_pct = pct
                            try:
                                on_progress(pct)
                            except Exception:
                                pass
        except Exception:
            pass
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

        code = proc.wait()
        with self._lock:
            self.proc = None

        if self._stop_requested:
            return -2

        if code == 0 and on_progress and duration and duration > 0:
            try:
                on_progress(100.0)
            except Exception:
                pass
        return code

    def tail(self, lines=12):
        """最近几行 ffmpeg 输出,失败时报错用。"""
        return "\n".join(self.last_stderr[-lines:])


__all__ = [
    "FFmpegRunner", "find_ffmpeg", "find_ffprobe", "probe_duration",
    "probe_media", "verify_output", "HARDWARE_CODECS",
    "_cmd_to_argv", "_seconds_from_progress_line", "_is_ffmpeg_argv",
]
