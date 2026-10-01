"""Verify the signed program-release manifest."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization


_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAQKOZna9f3CiWIQvYgKyZGlN/9eZAYci833gQSc8RwMk=
-----END PUBLIC KEY-----
"""


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def verify_release_manifest(root: Path, required: bool | None = None) -> dict:
    if required is None:
        required = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
    manifest_path = root / "manifest.json"
    signature_path = root / "manifest.sig"
    if not manifest_path.is_file() or not signature_path.is_file():
        if required:
            raise RuntimeError("发布包缺少 manifest.json 或 manifest.sig")
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        signature = base64.b64decode(signature_path.read_text(encoding="ascii").strip(), validate=True)
        serialization.load_pem_public_key(_PUBLIC_KEY).verify(signature, _canonical(manifest))
    except Exception as exc:
        raise RuntimeError("发布包签名无效") from exc
    if manifest.get("product_id") != "xinghu-juchang" or int(manifest.get("schema") or 0) != 1:
        raise RuntimeError("发布包产品或版本无效")
    for item in manifest.get("files") or []:
        relative = Path(str(item.get("path") or ""))
        target = (root / relative).resolve()
        if not relative.parts or relative.is_absolute() or ".." in relative.parts or not target.is_file():
            raise RuntimeError(f"发布文件缺失：{relative}")
        if target.stat().st_size != int(item.get("size") or -1) or _sha256(target) != item.get("sha256"):
            raise RuntimeError(f"发布文件已被篡改：{relative}")
    return manifest
