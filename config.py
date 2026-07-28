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
    moving_sticker_folder: str = ""
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
    pip_move_speed: int = 30
    pip2_enabled: bool = False
    pip2_scale: int = 15
    pip2_opacity: int = 25
    pip2_x: int = 78
    pip2_y: int = 78
    pip2_move: bool = False
    pip2_move_speed: int = 30
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
    cover_y: int = 50
    subtitle_enabled: bool = False
    subtitle_export_srt: bool = False
    subtitle_model: str = "small"
    subtitle_style: str = "经典白字黑边"
    subtitle_font_size: int = 28
    subtitle_max_chars: int = 10
    subtitle_pos_y: int = 78

    # ── 人脸、调色与后处理 ──
    face_blur_enabled: bool = False
    face_blur_strength: int = 35
    face_blur_expand: int = 100
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
    mp4_track_id: int = 89757
    mp4_layer_video: int = 0
    mp4_layer_audio: int = 256
    mp4_elst_ms: int = 0

    # ── 序列化 ──

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        if "folders" in data and "params" in data:
            return cls.from_reference_dict(data)
        # 只取已知字段，忽略未知
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def from_reference_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Convert the reference application's nested preset format."""
        folders = data.get("folders", {})
        params = data.get("params", {})
        options = data.get("options", {})
        encoding = data.get("encoding", {})
        color = data.get("color", {})
        mp4 = data.get("mp4tool", {})

        values: Dict[str, Any] = {
            "main_folder": folders.get("main_folder", ""),
            "background_folder": folders.get("aux_folder", ""),
            "sticker_folder": folders.get("watermark_folder", ""),
            "moving_sticker_folder": folders.get("endcard_folder", ""),
            "kaimu_folder": options.get("ai_download_folder", ""),
            "scanlight_folder": folders.get("endcard_folder", ""),
            "output_folder": folders.get("output_folder", ""),
            "repeat_count": options.get("repeat_count", 1),
            "delete_used_aux": options.get("delete_used_aux", False),
            "main_fit": options.get("main_fit", True),
            "mask_enabled": options.get("mask_step_enabled", False),
            "top_step_enabled": options.get("top_step_enabled", False),
            "bars_enabled": options.get("bars_step_enabled", False),
            "pip_enabled": options.get("pip_step_enabled", False),
            "pip_move": options.get("pip_move_enabled", False),
            "pip2_enabled": options.get("pip2_step_enabled", False),
            "pip2_move": options.get("pip2_move_enabled", False),
            "split_bars_enabled": (
                options.get("tb_split_enabled", False)
                or options.get("bb_split_enabled", False)
            ),
            "moving_sticker_enabled": options.get("mover_enabled", False),
            "sticker_enabled": options.get("watermark_enabled", False),
            "scanlight_enabled": options.get("scanlight_enabled", False),
            "kaimu_enabled": options.get("kaimu_enabled", False),
            "kaimu_mode": options.get("kaimu_choice", "素材-随机"),
            "line_enabled": options.get("line_enabled", False),
            "line_style_choice": options.get("line_style_choice", "十字-点线"),
            "face_blur_enabled": options.get("face_blur_enabled", False),
            "subtitle_enabled": options.get("sub_enabled", False),
            "subtitle_export_srt": options.get("sub_export_srt", False),
            "subtitle_style": options.get("sub_template", "经典白字黑边"),
            "subtitle_model": str(options.get("sub_model", "small")).split()[0],
            "cover_enabled": options.get("cover_enabled", False),
            "cover_follow_name": options.get("cover_follow_name", True),
            "cover_text": options.get("cover_text", ""),
            "resolution": encoding.get("resolution", "1080x1920"),
            "fps": int(encoding.get("fps", 30)),
            "crf": int(encoding.get("crf", 23)),
            "preset": encoding.get("preset", "medium"),
            "compose_threads": int(encoding.get("compose_threads", 4)),
            "gpu": encoding.get("gpu_enabled", False),
            "hevc": encoding.get("hevc", False),
            "filter_name": (
                color.get("filter_name", "") if color.get("filter_enabled") else ""
            ),
            "filter_strength": color.get("filter_strength", 100),
            "brightness": color.get("bri", 0) if color.get("adjust_enabled") else 0,
            "contrast": color.get("con", 0) if color.get("adjust_enabled") else 0,
            "saturation": color.get("sat", 0) if color.get("adjust_enabled") else 0,
            "temperature": color.get("temp", 0) if color.get("adjust_enabled") else 0,
            "vignette": color.get("vig", 0) if color.get("adjust_enabled") else 0,
            "mp4_enabled": mp4.get("enabled", False),
            "mp4_hevc": mp4.get("encode", False),
            "mp4_random_size": mp4.get("size_check", False),
            "mp4_id_follow": mp4.get("id_follow", False),
            "mp4_track_id": int(mp4.get("id", 89757)),
            "mp4_layer_video": int(mp4.get("layer_vid", 0)),
            "mp4_layer_audio": int(mp4.get("layer_aud", 256)),
            "mp4_elst_ms": int(mp4.get("elst", 0)) if mp4.get("elst_check") else 0,
            "sticker_layers_json": json.dumps(
                data.get("watermark_layers", []), ensure_ascii=False
            ),
            "mover_layers_json": json.dumps(
                data.get("mover_layers", []), ensure_ascii=False
            ),
        }
        aliases = {
            "main_scale": "main_scale", "aux_scale": "aux_scale",
            "aux_speed": "aux_speed", "mask_margin_tb": "mask_margin_tb",
            "mask_margin_lr": "mask_margin_lr", "mask_feather": "mask_feather",
            "top_scale": "top_scale", "top_opacity": "top_opacity",
            "top_feather": "top_feather", "top_bar_height": "top_bar_height",
            "top_bar_opacity": "top_bar_opacity",
            "top_bar_feather_down": "top_bar_feather_down",
            "bottom_bar_height": "bottom_bar_height",
            "bottom_bar_opacity": "bottom_bar_opacity",
            "bottom_bar_feather_up": "bottom_bar_feather_up",
            "pip_scale": "pip_scale", "pip_opacity": "pip_opacity",
            "pip_x": "pip_x", "pip_y": "pip_y",
            "pip_move_speed": "pip_move_speed", "pip2_scale": "pip2_scale",
            "pip2_opacity": "pip2_opacity", "pip2_x": "pip2_x",
            "pip2_y": "pip2_y", "pip2_move_speed": "pip2_move_speed",
            "tb_split_feather": "tb_split_feather",
            "bb_split_feather": "bb_split_feather",
            "scanlight_speed": "scanlight_speed",
            "scanlight_opacity": "scanlight_opacity",
            "kaimu_speed": "kaimu_speed", "wm_switch_sec": "sticker_switch_sec",
            "line_opacity": "line_opacity", "line_y": "line_y",
            "line_x": "line_x", "line_width": "line_width",
            "face_blur_strength": "face_blur_strength",
            "face_blur_expand": "face_blur_expand",
            "face_blur_detect_every": "face_detect_every",
            "sub_font_size": "subtitle_font_size",
            "sub_pos_y": "subtitle_pos_y", "sub_max_chars": "subtitle_max_chars",
            "cover_size": "cover_size", "cover_y": "cover_y",
            "main_zoom_amp": "zoom_amp", "main_sway_amp": "sway_amp",
            "main_shake_amp": "shake_amp",
        }
        for source, target in aliases.items():
            if source in params:
                values[target] = params[source]
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})

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
