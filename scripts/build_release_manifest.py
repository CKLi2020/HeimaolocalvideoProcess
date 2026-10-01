"""Generate and Ed25519-sign the program release manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--core", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--build-id", required=True)
    args = parser.parse_args()
    root = Path(args.release_root).resolve()

    def item(path: Path) -> dict:
        path = path.resolve()
        return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path), "size": path.stat().st_size}

    manifest = {
        "schema": 1,
        "product_id": "xinghu-juchang",
        "build_id": args.build_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [item(Path(args.exe)), item(Path(args.core))],
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = serialization.load_pem_private_key(Path(args.private_key).read_bytes(), password=None)
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "manifest.sig").write_text(base64.b64encode(key.sign(canonical)).decode("ascii"), encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
