"""字幕引擎：语音识别 → SRT/ASS 生成 → 字幕烧录。

依赖 faster-whisper（需 pip install faster-whisper）。
运行时自动检测，未安装时给出明确提示。
"""

from __future__ import annotations

import os
import copy
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# ── 运行时检测 ──
_FASTER_WHISPER_OK = False
_WHISPER_IMPORT_ERROR = ""

try:
    from faster_whisper import WhisperModel, BatchedInferencePipeline

    _FASTER_WHISPER_OK = True
except ImportError as e:
    _WHISPER_IMPORT_ERROR = str(e)
    # 尝试标准 whisper 作为 fallback
    try:
        import whisper as _openai_whisper

        _FASTER_WHISPER_OK = False  # 仍然用 faster 标记，但有 fallback
    except ImportError:
        pass


# ── 字幕样式预设 ──
class SubtitleStyle:
    """字幕样式定义，可输出为 ASS Format 或 ffmpeg drawtext 参数。"""

    def __init__(
        self,
        name: str,
        font_name: str = "Microsoft YaHei",
        font_size: int = 28,
        primary_color: str = "&H00FFFFFF",  # ASS 颜色格式: &HAABBGGRR
        outline_color: str = "&H00000000",
        outline_width: float = 2.5,
        shadow_depth: float = 1.0,
        alignment: int = 2,  # 底部居中
        margin_v: int = 60,
        margin_l: int = 30,
        margin_r: int = 30,
    ):
        self.name = name
        self.font_name = font_name
        self.font_size = font_size
        self.primary_color = primary_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.shadow_depth = shadow_depth
        self.alignment = alignment
        self.margin_v = margin_v
        self.margin_l = margin_l
        self.margin_r = margin_r

    def to_ass_style(self) -> str:
        """生成 ASS Style 定义行。"""
        return (
            f"Style: Default,{self.font_name},{self.font_size},"
            f"{self.primary_color},{self.primary_color},"
            f"&H00000000,&H00000000,0,0,0,0,100,100,"
            f"{self.shadow_depth},0,{self.outline_width},"
            f"{self.outline_color},{self.alignment},"
            f"{self.margin_l},{self.margin_r},{self.margin_v},0"
        )


# 预设样式
STYLE_CLASSIC = SubtitleStyle(
    "经典白字黑边",
    font_name="Microsoft YaHei",
    font_size=28,
    primary_color="&H00FFFFFF",
    outline_color="&H00000000",
    outline_width=2.5,
)

STYLE_JIANYING = SubtitleStyle(
    "剪映式短句",
    font_name="Microsoft YaHei",
    font_size=32,
    primary_color="&H00FFFFFF",
    outline_color="&H88000000",
    outline_width=1.5,
    shadow_depth=0.5,
    alignment=2,
    margin_v=80,
)

STYLE_MIAOJIAN = SubtitleStyle(
    "秒剪风格",
    font_name="Microsoft YaHei",
    font_size=24,
    primary_color="&H00FFFFCC",
    outline_color="&H88000000",
    outline_width=1.0,
    alignment=2,
    margin_v=50,
)


def get_style(name: str) -> SubtitleStyle:
    """根据名称获取字幕样式。"""
    styles = {
        "经典白字黑边": STYLE_CLASSIC,
        "剪映式短句": STYLE_JIANYING,
        "秒剪风格": STYLE_MIAOJIAN,
    }
    return copy.copy(styles.get(name, STYLE_CLASSIC))


# ═══════════════════════════════════════════════════
# 字幕引擎核心
# ═══════════════════════════════════════════════════


class SubtitleEngine:
    """语音识别字幕引擎。"""

    def __init__(
        self,
        model_size_or_path: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            model_size_or_path: 模型名称 ("tiny","small","medium","large")
                               或本地路径
            device: "auto", "cpu", "cuda"
            compute_type: "auto", "int8", "float16", "float32"
            log_callback: 日志回调
        """
        self._model_path = model_size_or_path
        self._device = device
        self._compute_type = compute_type
        self._log = log_callback or print
        self._model: Optional[WhisperModel] = None
        self._available = _FASTER_WHISPER_OK

    @property
    def is_available(self) -> bool:
        return self._available

    def _resolve_model_path(self) -> str:
        """将模型名称解析为实际路径。优先使用本地模型。"""
        # 如果已经是存在的路径，直接使用
        path = Path(self._model_path)
        if path.is_dir() and (path / "model.bin").exists():
            return str(path.resolve())

        # 检查标准模型名称 → 本地路径映射
        local_candidates = [
            Path(__file__).parent.parent.parent / "models" / f"faster-whisper-{self._model_path}",
            Path.cwd() / "models" / f"faster-whisper-{self._model_path}",
        ]
        local_candidates.extend(
            reference / "models" / f"faster-whisper-{self._model_path}"
            for reference in Path.cwd().parent.glob("风无忧剪辑软件V1.6_1/*")
        )
        for candidate in local_candidates:
            if candidate.is_dir() and (candidate / "model.bin").exists():
                self._log(f"[字幕] 使用本地模型: {candidate}")
                return str(candidate)

        # 回退：让 faster-whisper 从 HuggingFace 下载
        self._log(f"[字幕] 本地未找到模型，将从 HuggingFace 加载: {self._model_path}")
        return self._model_path

    def _ensure_model(self) -> bool:
        """确保模型已加载。返回 True 表示可用。"""
        if not self._available:
            self._log(f"[字幕] faster-whisper 未安装 ({_WHISPER_IMPORT_ERROR})")
            self._log("[字幕] 请运行: pip install faster-whisper")
            return False

        if self._model is not None:
            return True

        try:
            resolved = self._resolve_model_path()
            self._log(f"[字幕] 正在加载语音模型: {resolved} ...")
            self._model = WhisperModel(
                resolved,
                device=self._device,
                compute_type=self._compute_type,
            )
            self._log("[字幕] 模型加载完成")
            return True
        except Exception as e:
            self._log(f"[字幕] 模型加载失败: {e}")
            self._available = False
            return False

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = "zh",
        vad_filter: bool = True,
    ) -> Tuple[List[dict], str]:
        """转写音频文件。

        Args:
            audio_path: 音频文件路径（WAV 16kHz mono 最佳）
            language: 语言代码，None 为自动检测
            vad_filter: 启用 VAD 过滤静音段

        Returns:
            (segments, detected_language)
            每个 segment: {"start": float, "end": float, "text": str}
        """
        if not self._ensure_model():
            return [], ""

        self._log(f"[字幕] 开始语音识别: {audio_path.name}")
        segments_out = []
        detected_lang = ""

        try:
            segments, info = self._model.transcribe(
                str(audio_path),
                language=language,
                vad_filter=vad_filter,
                beam_size=5,
                best_of=5,
            )
            detected_lang = info.language
            self._log(f"[字幕] 检测到语言: {detected_lang}, 概率: {info.language_probability:.2f}")

            for seg in segments:
                segments_out.append({
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "text": seg.text.strip(),
                })

            self._log(f"[字幕] 识别完成: {len(segments_out)} 个片段, "
                      f"总时长 {segments_out[-1]['end']:.1f}s" if segments_out else "[字幕] 未识别到语音")
        except Exception as e:
            self._log(f"[字幕] 识别失败: {e}")

        return segments_out, detected_lang


def extract_audio(
    video_path: Path,
    output_dir: Optional[Path] = None,
    sample_rate: int = 16000,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """从视频提取音频为 16kHz mono WAV（whisper 最佳输入）。

    Returns:
        WAV 文件路径，失败返回 None
    """
    log = log_callback or print
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log("[字幕] 找不到 ffmpeg")
        return None

    if output_dir is None:
        output_dir = Path(tempfile.gettempdir())

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_path = output_dir / f"{video_path.stem}_audio_{os.getpid()}.wav"

    log(f"[字幕] 提取音频: {video_path.name} → {wav_path.name}")
    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-vn",  # 不要视频
        "-acodec", "pcm_s16le",  # PCM 16-bit
        "-ar", str(sample_rate),  # 16kHz
        "-ac", "1",  # mono
        str(wav_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log(f"[字幕] 音频提取失败: {result.stderr[-300:]}")
            return None
        if wav_path.stat().st_size < 1000:
            log("[字幕] 提取的音频文件过小，可能视频无音频轨")
            return None
        return wav_path
    except Exception as e:
        log(f"[字幕] 音频提取异常: {e}")
        return None


def generate_srt(segments: List[dict], output_path: Path) -> bool:
    """将识别片段生成 SRT 字幕文件。

    Args:
        segments: [{"start": 0.0, "end": 1.5, "text": "..."}, ...]
        output_path: 输出 .srt 文件路径

    Returns:
        True 表示成功
    """
    if not segments:
        return False

    def _fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{_fmt_time(seg['start'])} --> {_fmt_time(seg['end'])}\n")
                f.write(f"{seg['text']}\n\n")
        return True
    except OSError:
        return False


def generate_ass(
    segments: List[dict],
    output_path: Path,
    style: SubtitleStyle = STYLE_CLASSIC,
    video_width: int = 1080,
    video_height: int = 1920,
) -> bool:
    """生成 ASS (Advanced SubStation Alpha) 字幕文件，带完整样式。

    ASS 格式对中文支持比 SRT 好，ffmpeg 的 ass/subtitles 滤镜可直接烧录。
    """
    if not segments:
        return False

    def _fmt_ass_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

    header = f"""[Script Info]
Title: FlowCut Studio Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style.to_ass_style()}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = ""
    for seg in segments:
        start = _fmt_ass_time(seg["start"])
        end = _fmt_ass_time(seg["end"])
        # 转义 ASS 特殊字符
        text = seg["text"].replace("{", "\\{").replace("}", "\\}").replace("\n", r"\N")
        events += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"

    try:
        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write(header + events)
        return True
    except OSError:
        return False


def burn_subtitles(
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    log_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """将字幕烧录到视频中（二次编码）。

    Args:
        video_path: 输入视频
        subtitle_path: .ass 或 .srt 字幕文件
        output_path: 输出视频
        log_callback: 日志回调

    Returns:
        True 表示成功
    """
    log = log_callback or print
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log("[字幕] 找不到 ffmpeg")
        return False

    sub_ext = subtitle_path.suffix.lower()
    escaped_path = (
        subtitle_path.resolve().as_posix()
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
    if sub_ext == ".ass":
        vf = f"ass=filename='{escaped_path}'"
    else:
        vf = f"subtitles=filename='{escaped_path}':force_style='FontSize=28,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2.5'"

    log(f"[字幕] 烧录字幕到视频: {output_path.name}")
    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "medium",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log(f"[字幕] 烧录失败: {result.stderr[-300:]}")
            return False
        return True
    except Exception as e:
        log(f"[字幕] 烧录异常: {e}")
        return False
