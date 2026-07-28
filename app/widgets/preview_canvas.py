"""预览画布：支持拖拽贴纸、滚轮缩放、防抖刷新预览帧。"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
from PySide6.QtCore import Qt, QTimer, QPoint, QRect
from config import AppConfig


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
        self._pixmap: Optional[QPixmap] = None
        self._sticker_rects: list[QRect] = []  # 贴纸边界框
        self._dragging_idx: int = -1
        self._drag_start: QPoint = QPoint()
        self._orig_x: int = 0
        self._orig_y: int = 0

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
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
        self._label.setText(
            '<div style="text-align:center;color:#64748b;padding:40px;">'
            '<div style="font-size:36px;color:#6366f1;">▶</div>'
            '<div style="margin-top:16px;">选择素材后可预览<br/>'
            '<span style="font-size:10px;">拖拽贴纸调整位置 | 滚轮缩放</span></div>'
            "</div>"
        )

    def schedule_refresh(self) -> None:
        """参数改动后调用，防抖刷新。"""
        self._debounce.start()

    def _refresh_preview(self) -> None:
        """用 ffmpeg 生成一帧预览图。"""
        main_folder = self._resolve(self._config.main_folder)
        bg_folder = self._resolve(self._config.background_folder)

        main_files = list(main_folder.glob("*")) if main_folder.is_dir() else []
        bg_files = list(bg_folder.glob("*")) if bg_folder.is_dir() else []

        if not main_files or not bg_files:
            return

        import random
        main_v = random.choice(main_files)
        bg_v = random.choice(bg_files)

        try:
            from engine.ffmpeg_builder import (
                IMAGE_EXTS, VIDEO_EXTS, build_ffmpeg_command, list_media,
            )
            stickers = list_media(
                str(self._resolve(self._config.sticker_folder)),
                VIDEO_EXTS | IMAGE_EXTS,
            )
            movers = list_media(
                str(self._resolve(
                    self._config.moving_sticker_folder
                    or self._config.sticker_folder
                )),
                VIDEO_EXTS | IMAGE_EXTS,
            )
            scanlights = list_media(
                str(self._resolve(self._config.scanlight_folder)), VIDEO_EXTS
            )
            openings = list_media(
                str(self._resolve(self._config.kaimu_folder)),
                VIDEO_EXTS | IMAGE_EXTS,
            )

            with tempfile.TemporaryDirectory() as tmp:
                video = Path(tmp) / "preview.mp4"
                image = Path(tmp) / "preview.png"
                cmd = build_ffmpeg_command(
                    self._config, main_v, bg_v, video,
                    sticker_files=stickers or None,
                    scanlight_file=scanlights[0] if scanlights else None,
                    kaimu_file=openings[0] if openings else None,
                    mover_files=movers or None,
                )
                subprocess.run(cmd, capture_output=True, timeout=30, check=True)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(video), "-frames:v", "1", str(image)],
                    capture_output=True, timeout=10, check=True,
                )
                if image.stat().st_size > 100:
                    self._show_pixmap(QPixmap(str(image)))
        except Exception:
            pass

    def _show_pixmap(self, pm: QPixmap) -> None:
        self._pixmap = pm.scaled(
            self._label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._label.setPixmap(self._pixmap)

    # ── 拖拽 + 滚轮 ──

    def _on_mouse_press(self, ev) -> None:
        if not self._pixmap:
            return
        pos = ev.pos()
        layers = self._get_layers()
        for i, layer in enumerate(layers):
            rx = int(self._label.width() * layer.get("x", 50) / 100)
            ry = int(self._label.height() * layer.get("y", 50) / 100)
            rs = int(30 * layer.get("scale", 20) / 20)
            if abs(pos.x() - rx) < rs and abs(pos.y() - ry) < rs:
                self._dragging_idx = i
                self._drag_start = pos
                self._orig_x = layer.get("x", 50)
                self._orig_y = layer.get("y", 50)
                self._label.setCursor(Qt.ClosedHandCursor)
                return

    def _on_mouse_move(self, ev) -> None:
        if self._dragging_idx < 0:
            return
        delta = ev.pos() - self._drag_start
        dx = int(delta.x() / self._label.width() * 100)
        dy = int(delta.y() / self._label.height() * 100)
        new_x = max(0, min(100, self._orig_x + dx))
        new_y = max(0, min(100, self._orig_y + dy))
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
            rx = int(self._label.width() * layer.get("x", 50) / 100)
            ry = int(self._label.height() * layer.get("y", 50) / 100)
            rs = int(30 * layer.get("scale", 20) / 20)
            if abs(pos.x() - rx) < rs and abs(pos.y() - ry) < rs:
                new_scale = max(5, min(200, layer.get("scale", 20) + delta * 3))
                self._update_layer(i, scale=new_scale)
                return

    # ── 辅助 ──

    def _resolve(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self._root / p

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

    def _update_layer(self, idx: int, **kwargs) -> None:
        layers = self._get_layers()
        if idx < len(layers):
            layers[idx].update(kwargs)
        self._config.sticker_layers_json = json.dumps(layers, ensure_ascii=False)
        self.schedule_refresh()
