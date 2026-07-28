"""配置数据结构、默认值和序列化。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict


@dataclass
class AppConfig:
    """完整应用配置，与 GUI 标签页一一对应。"""

    # ── 文件与批量 ──
    main_folder: str = ""
    background_folder: str = ""
    sticker_folder: str = ""
    scanlight_folder: str = ""
    kaimu_folder: str = ""
    output_folder: str = ""
    repeat_count: int = 1
    delete_used_aux: bool = False

    # ── 画布与编码 ──
    resolution: str = "1080x1920"
    fps: int = 30
    main_scale: int = 105
    main_fit: bool = True
    aux_scale: int = 100
    aux_speed: int = 100
    gpu: bool = False
    hevc: bool = False
    crf: int = 23
    preset: str = "medium"
    compose_threads: int = 4

    # ── 蒙版与横条 ──
    mask_enabled: bool = True
    mask_margin_tb: int = 1
    mask_margin_lr: int = 2
    mask_feather: int = 15
    top_step_enabled: bool = False
    top_scale: int = 60
    top_opacity: int = 3
    top_feather: int = 20
    bars_enabled: bool = False
    bar_height: int = 300
    bar_opacity: int = 40
    top_bar_height: int = 300
    top_bar_opacity: int = 43
    top_bar_feather_down: int = 45
    bottom_bar_height: int = 300
    bottom_bar_opacity: int = 38
    bottom_bar_feather_up: int = 35
    split_bars_enabled: bool = False
    split_feather: int = 40
    tb_split_feather: int = 40
    bb_split_feather: int = 40
    line_enabled: bool = False
    line_style_choice: str = "十字-点线"
    line_opacity: int = 60
    line_x: int = 50
    line_y: int = 46
    line_width: int = 2

    # ── 画中画与动态 ──
    pip_enabled: bool = False
    pip_scale: int = 15
    pip_opacity: int = 40
    pip_x: int = 8
    pip_y: int = 10
    pip_move: bool = False
    pip2_enabled: bool = False
    pip2_scale: int = 15
    pip2_opacity: int = 25
    pip2_x: int = 78
    pip2_y: int = 78
    pip2_move: bool = False
    zoom_amp: int = 0
    sway_amp: int = 0
    shake_amp: int = 0

    # ── 贴纸与扫光 ──
    sticker_enabled: bool = True
    sticker_scale: int = 20
    sticker_opacity: int = 60
    sticker_x: int = 80
    sticker_y: int = 8
    sticker_switch_sec: int = 0
    # 多层贴纸 JSON 数组: [{"scale":20,"opacity":60,"x":80,"y":8}, ...]
    # 如果非空则覆盖上面的单层参数
    sticker_layers_json: str = ""
    moving_sticker_enabled: bool = False
    moving_sticker_period: int = 8
    # 移动贴纸层 JSON 数组
    mover_layers_json: str = ""
    scanlight_enabled: bool = True
    scanlight_opacity: int = 45
    scanlight_speed: int = 100

    # ── 开幕、封面与字幕 ──
    kaimu_enabled: bool = False
    kaimu_mode: str = "素材-随机"
    kaimu_speed: int = 100
    cover_enabled: bool = False
    cover_follow_name: bool = True
    cover_text: str = ""
    cover_size: int = 60
    subtitle_enabled: bool = False
    subtitle_export_srt: bool = False
    subtitle_model: str = "small"
    subtitle_style: str = "经典白字黑边"
    subtitle_font_size: int = 28
    subtitle_max_chars: int = 10

    # ── 人脸、调色与后处理 ──
    face_blur_enabled: bool = False
    face_blur_strength: int = 35
    face_detect_every: int = 1
    brightness: int = 0
    contrast: int = 0
    saturation: int = 0
    temperature: int = 0
    vignette: int = 0
    filter_name: str = ""
    filter_strength: int = 100
    mp4_enabled: bool = False
    mp4_hevc: bool = False
    mp4_random_size: bool = False
    mp4_id_follow: bool = False
    mp4_layer_video: int = 0
    mp4_layer_audio: int = 256
    mp4_elst_ms: int = 0

    # ── 序列化 ──

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        # 只取已知字段，忽略未知
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def from_json(cls, path: Path) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


# 默认配置实例
DEFAULT_CONFIG = AppConfig()
