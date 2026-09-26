"""预览画布：支持拖拽贴纸、滚轮缩放、防抖刷新预览帧。"""

from __future__ import annotations

import json
import copy
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QFont
from PySide6.QtCore import Qt, QTimer, QPoint, QRect
from config import AppConfig
from engine import HIDDEN_SUBPROCESS


class PreviewCanvas(QWidget):
    """交互式预览画布。

    功能:
    - 点击拖拽贴纸调整位置
    - 滚轮缩放贴纸
    - 参数改动防抖后自动刷新预览帧
    """

    def __init__(
        self,
        config: AppConfig,
        root_dir: Path,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._config = config
        self._root = root_dir
        self._task: Optional[dict] = None
        self._pixmap: Optional[QPixmap] = None
        self._face_engine = None
        self._sticker_rects: list[QRect] = []  # 贴纸边界框
        self._dragging_idx: int = -1
        self._drag_start: QPoint = QPoint()
        self._orig_x: int = 0
        self._orig_y: int = 0

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._refresh_preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel()
        self._label.setObjectName("preview")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMinimumSize(260, 420)
        self._label.setMouseTracking(True)
        self._label.mousePressEvent = self._on_mouse_press
        self._label.mouseMoveEvent = self._on_mouse_move
        self._label.mouseReleaseEvent = self._on_mouse_release
        self._label.wheelEvent = self._on_wheel
        layout.addWidget(self._label)

        self.show_placeholder()

    def show_placeholder(self) -> None:
        self._pixmap = None
        self._label.setPixmap(QPixmap())
        self._label.setText(
            '<div style="text-align:center;color:#4a6088;padding:40px;">'
            '<div style="font-size:42px;color:#3b82f6;margin-bottom:6px;">▶</div>'
            '<div style="font-size:13px;color:#7a95c0;font-weight:500;">选择素材后可预览</div>'
            '<div style="margin-top:10px;font-size:10px;color:#4a6088;">'
            '拖拽贴纸调整位置 &nbsp;|&nbsp; 滚轮缩放贴纸</div>'
            "</div>"
        )

    def schedule_refresh(self) -> None:
        """参数改动后调用，防抖刷新。"""
        self._debounce.start()

    def show_task(self, task: dict) -> None:
        """Preview the exact media selected for the current batch job."""
        self._task = task
        self.schedule_refresh()

    def _refresh_preview(self) -> None:
        """用 ffmpeg 生成一帧预览图。"""
        from engine.ffmpeg_builder import (
            IMAGE_EXTS, VIDEO_EXTS, build_ffmpeg_command, list_media,
        )
        task = self._task
        main_files = (
            [Path(task["main"])] if task else
            list_media(str(self._resolve(self._config.main_folder)), VIDEO_EXTS)
        )
        if task:
            # 没有辅助视频时 task["background"] 是 None（引擎会用纯色画布兜底），
            # 直接 Path(None) 会抛 TypeError，所以先判空。
            bg_files = [Path(task["background"])] if task["background"] else []
        else:
            bg_files = list_media(
                str(self._resolve(self._config.background_folder)), VIDEO_EXTS
            )
            if self._config.tpl_pick == "固定" and self._config.tpl_fixed:
                fixed = next(
                    (path for path in bg_files if path.name == self._config.tpl_fixed),
                    None,
                )
                if fixed is not None:
                    bg_files = [fixed]

        if not main_files and not bg_files:
            self.show_placeholder()
            return

        main_v = main_files[0] if main_files else None
        bg_v = bg_files[0] if bg_files else None

        # 模板模式下模板即背景，需在下面的空背景判断之前替换，
        # 否则背景目录为空时预览会退回单帧、看不到模板效果。
        # 选哪一张：选了「固定」就必须预览那一张（成品每次都用它，预览用别的就
        # 说的是两回事）；「随机」时固定取列表第一个，不调 pick() —— 每次刷新
        # 换一张的话预览会闪，调窗口几何时失去稳定参照。
        template_window = None
        if self._config.tpl_enabled:
            from engine.template_lib import load_library

            library = load_library(
                self._resolve(self._config.tpl_folder),
                self._config.tpl_manifest,
            )
            # 用 has() 而不是直接 pick()：pick 在没命中时会随机挑一张，预览就会
            # 每次刷新换一张、看着像坏了。没命中就走下面的 specs[0]，稳定。
            spec = None
            if self._config.tpl_pick == "固定" and library.has(self._config.tpl_fixed):
                spec = library.pick("固定", self._config.tpl_fixed)
            if spec is None and library.specs:
                spec = library.specs[0]
            if spec is not None:
                bg_v = spec.path
                template_window = library.resolve(spec, self._config)

        # 没有背景不再是「退回单帧」的理由：引擎本来就会用纯色画布出片，
        # 预览也照着渲染（build_ffmpeg_command 接受 background_video=None），
        # 否则预览显示的画面和成品对不上。只有连主视频都没有才退化成静帧。
        if not main_v:
            self._show_video_frame(bg_v)
            return

        try:
            if task:
                stickers = [
                    Path(path) for path in task["stickers"][:len(self._get_layers())]
                ]
                movers = [Path(path) for path in task["movers"]]
                # 轨道跟着任务走：这批片子的走位是出片时掷好的，预览照抄才对得上。
                # 关掉随机时任务里是 None，交给构建器回落到配置里的显式图层。
                mover_layers_for_cmd = task.get("mover_layers")
                scanlight = task["scanlight"]
                opening = task["kaimu"]
            else:
                sticker_pool = list_media(
                    str(self._resolve(self._config.sticker_folder)),
                    VIDEO_EXTS | IMAGE_EXTS,
                )
                sticker_layers = self._get_layers()
                stickers = [
                    sticker_pool[i % len(sticker_pool)]
                    for i in range(len(sticker_layers))
                ] if self._config.sticker_enabled and sticker_pool else []
                mover_pool = list_media(
                    str(self._resolve(
                        self._config.moving_sticker_folder
                        or self._config.sticker_folder
                    )),
                    VIDEO_EXTS | IMAGE_EXTS,
                )
                mover_layers_for_cmd = self._get_mover_layers()
                movers = [
                    mover_pool[i % len(mover_pool)]
                    for i in range(len(mover_layers_for_cmd))
                ] if self._config.moving_sticker_enabled and mover_pool else []
                scanlights = list_media(
                    str(self._resolve(self._config.scanlight_folder)), VIDEO_EXTS
                )
                openings = list_media(
                    str(self._resolve(self._config.kaimu_folder)),
                    VIDEO_EXTS | IMAGE_EXTS,
                )
                scanlight = scanlights[0] if scanlights else None
                opening = openings[0] if openings else None

            with tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / "preview.png"
                preview_config = copy.copy(self._config)
                preview_config.sticker_switch_sec = 0
                preview_config.kaimu_enabled = False
                # 静态画面预览不需要解码或混合音轨；声音设置在导出时生效。
                preview_config.audio_bgm_enabled = False
                preview_config.audio_voice_enabled = False
                preview_config.audio_voice_adaptive = False
                cmd = build_ffmpeg_command(
                    preview_config, main_v, bg_v, image,
                    sticker_files=stickers or None,
                    scanlight_file=scanlight,
                    kaimu_file=opening,
                    mover_files=movers or None,
                    template_window=template_window,
                    mover_layers=mover_layers_for_cmd,
                )
                cmd[cmd.index("-map"):] = [
                    "-map", "[next_v]", "-ss", "0.5",
                    "-frames:v", "1", str(image),
                ]
                subprocess.run(
                    cmd, capture_output=True, timeout=30, check=True,
                    **HIDDEN_SUBPROCESS,
                )
                if image.stat().st_size > 100:
                    self._apply_face_blur(image)
                    self._show_pixmap(QPixmap(str(image)))
        except Exception as exc:
            self._show_video_frame(main_v)
            self._label.setToolTip(f"完整叠加预览生成失败：{exc}")

    def _show_video_frame(self, video: Path) -> None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / "source.png"
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", "0.5", "-i", str(video),
                        "-frames:v", "1", str(image),
                    ],
                    capture_output=True, timeout=10, check=True,
                    **HIDDEN_SUBPROCESS,
                )
                if image.stat().st_size > 100:
                    self._apply_face_blur(image)
                    self._show_pixmap(QPixmap(str(image)))
                    return
        except Exception:
            pass
        self.show_placeholder()

    def _show_pixmap(self, pm: QPixmap) -> None:
        self._draw_subtitle_preview(pm)
        self._label.setToolTip("")
        self._pixmap = pm.scaled(
            self._label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._label.setPixmap(self._pixmap)

    def _apply_face_blur(self, image: Path) -> None:
        if not self._config.face_blur_enabled:
            return
        try:
            import cv2
            from engine.face_blur import FaceBlurEngine

            if self._face_engine is None:
                self._face_engine = FaceBlurEngine(log_callback=lambda _: None)
            self._face_engine._blur_strength = self._config.face_blur_strength
            self._face_engine._blur_expand = self._config.face_blur_expand
            frame = cv2.imread(str(image))
            faces = self._face_engine.detect_faces(frame)
            cv2.imwrite(str(image), self._face_engine.blur_faces(frame, faces))
        except Exception:
            pass

    def _draw_subtitle_preview(self, pm: QPixmap) -> None:
        if not self._config.subtitle_enabled or pm.isNull():
            return

        text = "这是字幕动态预览效果"
        width = max(1, self._config.subtitle_max_chars)
        lines = [text[i:i + width] for i in range(0, len(text), width)]
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(self._config.subtitle_font_size)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        y = int(pm.height() * self._config.subtitle_pos_y / 100)
        style_index = sum(map(ord, self._config.subtitle_style)) % 3
        color = (QColor("#ffffff"), QColor("#fde047"), QColor("#67e8f9"))[style_index]
        for index, line in enumerate(lines):
            x = (pm.width() - metrics.horizontalAdvance(line)) // 2
            line_y = y + index * line_height
            painter.setPen(QPen(QColor("#000000"), 5))
            painter.drawText(x, line_y, line)
            painter.setPen(color)
            painter.drawText(x, line_y, line)
        painter.end()

    # ── 拖拽 + 滚轮 ──

    def _on_mouse_press(self, ev) -> None:
        if not self._pixmap:
            return
        pos = ev.pos()
        layers = self._get_layers()
        for i, layer in enumerate(layers):
            rx, ry = self._layer_point(layer)
            rs = max(24, int(35 * layer.get("scale", 100) / 100))
            if abs(pos.x() - rx) < rs and abs(pos.y() - ry) < rs:
                self._dragging_idx = i
                self._drag_start = pos
                self._orig_x = layer.get("x", 0)
                self._orig_y = layer.get("y", 0)
                self._label.setCursor(Qt.ClosedHandCursor)
                return

    def _on_mouse_move(self, ev) -> None:
        if self._dragging_idx < 0:
            return
        delta = ev.pos() - self._drag_start
        dx = int(delta.x() / max(1, self._pixmap.width()) * 100)
        dy = int(delta.y() / max(1, self._pixmap.height()) * 100)
        new_x = max(-50, min(50, self._orig_x + dx))
        new_y = max(-50, min(50, self._orig_y + dy))
        self._update_layer(self._dragging_idx, x=new_x, y=new_y)

    def _on_mouse_release(self, ev) -> None:
        self._dragging_idx = -1
        self._label.setCursor(Qt.ArrowCursor)

    def _on_wheel(self, ev) -> None:
        if not self._pixmap:
            return
        pos = ev.position()
        delta = 1 if ev.angleDelta().y() > 0 else -1
        layers = self._get_layers()
        for i, layer in enumerate(layers):
            rx, ry = self._layer_point(layer)
            rs = max(24, int(35 * layer.get("scale", 100) / 100))
            if abs(pos.x() - rx) < rs and abs(pos.y() - ry) < rs:
                new_scale = max(5, min(200, layer.get("scale", 100) + delta * 3))
                self._update_layer(i, scale=new_scale)
                return

    # ── 辅助 ──

    def _resolve(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self._root / p

    def _layer_point(self, layer: dict) -> tuple[int, int]:
        """Map reference coordinates (-50..50) into the centered preview pixmap."""
        left = (self._label.width() - self._pixmap.width()) // 2
        top = (self._label.height() - self._pixmap.height()) // 2
        x = (layer.get("x", 0) + 50) / 100
        y = (layer.get("y", 0) + 50) / 100
        return (
            left + int(self._pixmap.width() * x),
            top + int(self._pixmap.height() * y),
        )

    def _get_layers(self) -> list[dict]:
        try:
            if self._config.sticker_layers_json:
                return json.loads(self._config.sticker_layers_json)
        except (json.JSONDecodeError, TypeError):
            pass
        return [{
            "scale": self._config.sticker_scale,
            "opacity": self._config.sticker_opacity,
            "x": self._config.sticker_x,
            "y": self._config.sticker_y,
        }]

    def _get_mover_layers(self) -> list[dict]:
        """预览用的移动贴纸轨道。

        和出片走的是同一个 build_mover_layers，只是「随机位置」这次掷出的结果
        预览没法预知成品那一条；这里也掷一份，但**缓存起来**，只在相关配置变了
        才重掷。否则调任何一个无关参数都会让预览里的贴纸跳位置，看着像坏了
        （同理见 _refresh_preview 里模板固定取第一个的注释）。
        """
        from engine.ffmpeg_builder import build_mover_layers

        try:
            explicit = (
                json.loads(self._config.mover_layers_json)
                if self._config.mover_layers_json else []
            )
            if not isinstance(explicit, list):
                explicit = []
        except (json.JSONDecodeError, TypeError):
            explicit = []

        # 键里要带上所有会改变轨道的输入，否则改了不重掷、预览和成品对不上：
        # 默认值来源是 mover_scale/mover_opacity（不是贴纸那套 sticker_*），
        # 数量与周期同理。
        key = (
            self._config.mover_random,
            self._config.mover_count,
            self._config.moving_sticker_period,
            self._config.mover_scale,
            self._config.mover_opacity,
            json.dumps(explicit, sort_keys=True),
        )
        if getattr(self, "_mover_key", None) != key:
            self._mover_layers = build_mover_layers(
                max(1, self._config.mover_count, len(explicit)),
                explicit,
                self._config.mover_scale,
                self._config.mover_opacity,
                self._config.moving_sticker_period,
                roll_positions=self._config.mover_random,
            )
            self._mover_key = key
        return self._mover_layers

    def _update_layer(self, idx: int, **kwargs) -> None:
        layers = self._get_layers()
        if idx < len(layers):
            layers[idx].update(kwargs)
        self._config.sticker_layers_json = json.dumps(layers, ensure_ascii=False)
        self.schedule_refresh()
