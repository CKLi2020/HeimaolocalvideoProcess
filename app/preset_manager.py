"""预设管理器：保存/加载/删除 JSON 预设文件。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from config import AppConfig


class PresetManager:
    """管理参数预设文件（JSON 格式）。"""

    def __init__(self, preset_dir: Path):
        self._dir = Path(preset_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def list_presets(self) -> List[str]:
        """列出所有预设名称（不含扩展名）。"""
        return sorted([
            p.stem for p in self._dir.glob("*.json")
        ])

    def load(self, name: str) -> Optional[AppConfig]:
        """加载指定预设。返回 None 表示失败。"""
        path = self._dir / f"{name}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AppConfig.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save(self, name: str, config: AppConfig) -> bool:
        """保存当前配置为预设。"""
        if not name.strip():
            return False
        path = self._dir / f"{name}.json"
        try:
            config.to_json(path)
            return True
        except OSError:
            return False

    def delete(self, name: str) -> bool:
        """删除指定预设。"""
        path = self._dir / f"{name}.json"
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False
