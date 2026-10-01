"""Shared output filename generation."""

from datetime import date
import re
import secrets
import string
from pathlib import Path


CHANNEL_FILENAME_PLATFORMS = frozenset({"douyin", "kuaishou", "shipinhao", "xiaohongshu"})
_TOKEN_ALPHABET = string.ascii_lowercase + string.digits


def output_name(source: Path) -> str:
    return f"{source.stem}_{date.today():%Y%m%d}_{secrets.token_hex(4).upper()}.mp4"


def channel_output_stem(source: Path, channel_name: str) -> str:
    safe_channel = re.sub(r'[<>:"/\\|?*]', "_", str(channel_name or "").strip())
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(4))
    return f"{source.stem}{safe_channel}{token}"
