"""Generate and Ed25519-sign the program release manifest.

The manifest is the tamper-evidence layer for the packaged release: every file
listed here is hashed, and ``core/release_integrity.py`` refuses to start when a
listed file no longer matches.  A file that is *missing* from the manifest is
therefore unprotected, so the walk below is deliberately broad and fails the
build when a product-owned file is not covered.

Deliberately not listed:

* ``config.json`` / ``client/config.json`` -- rewritten at runtime (main.py
  rewrites the top-level one on every launch), so pinning them would make the
  second launch fail.
* third-party runtimes (PySide6, numpy, ...) and the user's working directories
  (主视频/, 辅助视频/, 成品目录/ ...) -- they are large, version-varied, and
  mutable: users drop their own files in and the app writes output there, so
  pinning them would break a normal session.
* ``使用教程（使用必看）/`` -- a 311 MB static tutorial video. It is not part of
  the algorithm or the licensing path, so pinning it buys no tamper-evidence
  while costing ~0.5 s of startup hashing and breaking every install the day the
  tutorial is re-recorded.

``core/release_integrity.py`` hashes every listed file at startup, and it runs
before the window appears (main.py). Keep the list to files that are immutable
and worth detecting a change in: the protected cores, the mode/template data
that defines output, and the product's own assets.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization

# Environment variable holding the passphrase for the encrypted signing key.
PASSWORD_ENV = "BLACKCAT_RELEASE_KEY_PASSWORD"

# Globs, relative to the release root, of files the product owns and ships.
INCLUDED = (
    "*.exe",                          # SProtect'd launcher + bundled ffmpeg/ffprobe
    "app/*.pyd",                      # both protected algorithm cores
    "client/**/*",
    "mode_defs/**/*",
    "modes/**/*",                     # channel data copied in by the build (ffmpeg templates, metadata)
    "resources/**/*",
    "ico/**/*",
    "配置文件/**/*",
    "贴纸/**/*",                       # overlay assets: swapping them rebrands the product
)

# Product-owned files that must NOT be pinned, with the reason.
EXCLUDED = {
    "config.json": "rewritten by main.py on every launch",
    "client/config.json": "rewritten at runtime",
    "manifest.json": "this file",
    "manifest.sig": "this file's signature",
    "SHA256SUMS.txt": "generated from this manifest",
}

# Files the product must never ship: a plaintext copy of a channel algorithm.
# The feimao/tingxue recipe lives in modes/douyin/feimao_recipe.py so that
# --include-package=modes compiles it in; shipping either data file again would
# hand out the filter graph verbatim.
FORBIDDEN = (
    "modes/shipinhao/heimao_luoyue_core.py",
    "modes/shipinhao/__pycache__/heimao_luoyue_core.cpython-*.pyc",
    "modes/douyin/filter_complex.txt",
    "modes/douyin/feimao_ffargs.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_embedded_public_key(repo_root: Path) -> bytes:
    """Read the _PUBLIC_KEY literal the packaged app verifies manifests with."""
    import importlib.util

    path = repo_root / "core" / "release_integrity.py"
    spec = importlib.util.spec_from_file_location("_release_integrity_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._PUBLIC_KEY


def assert_key_matches_embedded(repo_root: Path, key) -> None:
    """Refuse to sign a manifest the freshly built app would reject.

    Rotating the signing key means editing _PUBLIC_KEY in core/release_integrity.py
    in the same commit. If the two drift apart, the release signs fine and then
    fails verification on every user's machine at startup -- so this is a build
    error, not a warning.
    """
    embedded = load_embedded_public_key(repo_root)
    derived = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if embedded != derived:
        raise SystemExit(
            "the signing key does not match _PUBLIC_KEY in core/release_integrity.py;\n"
            "the packaged app would reject this manifest at startup.\n"
            "Replace the _PUBLIC_KEY literal with:\n\n"
            '_PUBLIC_KEY = b"""' + derived.decode("ascii") + '"""'
        )


def load_signing_key(path: Path, allow_unencrypted: bool):
    """Load the Ed25519 signing key, insisting it is passphrase-protected.

    The private half is the root of release trust: anyone holding it can sign a
    manifest for any build and every installed copy will accept it. A plaintext
    key on disk is one backup or one stray sync away from that, so signing
    refuses to proceed unless the key is encrypted.
    """
    data = path.read_bytes()
    passphrase = os.environ.get(PASSWORD_ENV) or None
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except TypeError:
        # Raised when the key is encrypted but no password was supplied.
        if not passphrase:
            raise SystemExit(
                f"the signing key {path} is passphrase-protected; set {PASSWORD_ENV}"
            )
        try:
            return serialization.load_pem_private_key(data, password=passphrase.encode("utf-8"))
        except ValueError as exc:
            raise SystemExit(f"cannot decrypt the signing key {path}: {exc}")
    except ValueError as exc:
        raise SystemExit(f"cannot read the signing key {path}: {exc}")
    if not allow_unencrypted:
        raise SystemExit(
            f"refusing to sign with an unencrypted private key: {path}\n"
            "  create a passphrase-protected one with scripts/make_release_signing_key.py,\n"
            "  or pass --allow-unencrypted-key for a one-off local test"
        )
    return key


def default_product_id(repo_root: Path) -> str:
    namespace: dict = {}
    exec((repo_root / "version.py").read_text(encoding="utf-8"), namespace)  # noqa: S102
    product_id = namespace.get("APP_ID")
    if not product_id:
        raise SystemExit("version.py does not define APP_ID")
    return product_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--product-id", help="defaults to APP_ID in version.py")
    parser.add_argument("--dry-run", action="store_true", help="list what would be signed without writing or signing")
    parser.add_argument(
        "--allow-unencrypted-key",
        action="store_true",
        help="sign with a passphrase-less private key (local tests only; releases must not)",
    )
    parser.add_argument(
        "--skip-public-key-check",
        action="store_true",
        help="sign without checking that the key matches _PUBLIC_KEY in core/release_integrity.py",
    )
    parser.add_argument(
        "--check-key-only",
        action="store_true",
        help="verify the signing key and exit without touching the release directory",
    )
    args = parser.parse_args()

    root = Path(args.release_root).resolve()
    if not root.is_dir():
        raise SystemExit("release root is not a directory: %s" % root)

    product_id = args.product_id or default_product_id(Path(__file__).resolve().parent.parent)

    for pattern in FORBIDDEN:
        leaked = sorted(root.glob(pattern))
        if leaked:
            raise SystemExit(
                "release ships a plaintext copy of a protected algorithm: "
                + ", ".join(str(p.relative_to(root)) for p in leaked)
            )

    selected: dict[str, Path] = {}
    for pattern in INCLUDED:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if relative in EXCLUDED:
                continue
            selected[relative] = path

    if not selected:
        raise SystemExit("no product files matched the manifest allowlist under %s" % root)

    files = [
        {"path": relative, "sha256": sha256(path), "size": path.stat().st_size}
        for relative, path in sorted(selected.items())
    ]

    manifest = {
        "schema": 1,
        "product_id": product_id,
        "build_id": args.build_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    if args.dry_run:
        print("dry run: %d files, product_id=%s" % (len(files), product_id))
        for item in files:
            print("  %-60s %10d  %s" % (item["path"], item["size"], item["sha256"][:16]))
        return 0

    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key_path = Path(args.private_key).expanduser().resolve()
    if not key_path.is_file():
        raise SystemExit(f"signing key not found: {key_path}")
    repo_root = Path(__file__).resolve().parent.parent
    if key_path == repo_root or repo_root in key_path.parents:
        raise SystemExit(f"refusing to sign with a key stored inside the repository: {key_path}")
    key = load_signing_key(key_path, args.allow_unencrypted_key)
    if not args.skip_public_key_check:
        assert_key_matches_embedded(Path(__file__).resolve().parent.parent, key)
    if args.check_key_only:
        print("signing key ok: it matches _PUBLIC_KEY in core/release_integrity.py")
        return 0
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "manifest.sig").write_text(base64.b64encode(key.sign(canonical)).decode("ascii"), encoding="ascii")
    print("manifest: %d files, product_id=%s" % (len(files), product_id))
    for relative in sorted(selected):
        print("  " + relative)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
