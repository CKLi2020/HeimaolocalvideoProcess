"""Shared output filename generation."""

from datetime import date
import secrets
from pathlib import Path


def output_name(source: Path) -> str:
    return f"{source.stem}_{date.today():%Y%m%d}_{secrets.token_hex(4).upper()}.mp4"
