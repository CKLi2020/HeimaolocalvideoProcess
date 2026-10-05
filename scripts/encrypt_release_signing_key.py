"""Encrypt an existing plaintext release signing key in place.

`finalize_sprotect_release.ps1` refuses any signing key whose file does not say
ENCRYPTED, because the private half is the root of release trust: whoever holds
it can sign a manifest for any build and every installed copy will accept it.

`make_release_signing_key.py` is the wrong tool when the key material must stay
the same -- it generates a *new* keypair, which changes `_PUBLIC_KEY` in
`core/release_integrity.py`, which is compiled into the launcher, and therefore
forces a full rebuild plus a fresh SProtect pass. Use this script instead when
only the on-disk protection needs to change.

The public half is unchanged, so `core/release_integrity.py` needs no edit. That
is not taken on faith: the script reloads the encrypted key and checks the
derived public key against the literal in that file before it replaces anything.

Usage (from the repo root):

    py -3.9 scripts\\encrypt_release_signing_key.py

The passphrase is read from BLACKCAT_RELEASE_KEY_PASSWORD, or prompted for if
that is unset. It must not be blank.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_release_manifest import assert_key_matches_embedded  # noqa: E402

PASSWORD_ENV = "BLACKCAT_RELEASE_KEY_PASSWORD"
DEFAULT_KEY = Path.home() / ".blackcat-release" / "manifest-private.pem"


def read_passphrase() -> str:
    value = os.environ.get(PASSWORD_ENV)
    if value is not None:
        if not value:
            raise SystemExit(f"{PASSWORD_ENV} is set but empty; unset it to be prompted instead")
        return value
    if not sys.stdin.isatty():
        raise SystemExit(f"set {PASSWORD_ENV} to read the passphrase without a terminal")
    first = getpass.getpass("Passphrase to protect the signing key with: ")
    if not first:
        raise SystemExit("the passphrase must not be blank")
    if first != getpass.getpass("Repeat it: "):
        raise SystemExit("the passphrases did not match")
    return first


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default=str(DEFAULT_KEY), help="plaintext private key to encrypt")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    key_path = Path(args.key).expanduser().resolve()

    if not key_path.is_file():
        raise SystemExit(f"no such signing key: {key_path}")
    if key_path == repo_root or repo_root in key_path.parents:
        raise SystemExit(f"refusing to touch a signing key inside the repository: {key_path}")

    data = key_path.read_bytes()
    if b"ENCRYPTED" in data:
        raise SystemExit(
            f"{key_path} is already passphrase-protected; nothing to do.\n"
            "To replace the key itself, use scripts\\make_release_signing_key.py --force."
        )

    try:
        key = serialization.load_pem_private_key(data, password=None)
    except Exception as exc:
        raise SystemExit(f"could not read {key_path} as an unencrypted private key: {exc}") from exc

    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    passphrase = read_passphrase().encode("utf-8")
    encrypted = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase),
    )

    # Write beside the original, prove it loads and still derives the same public
    # key, and only then swap it in. A half-written key here would brick signing.
    staged = key_path.with_name(key_path.name + ".new")
    staged.write_bytes(encrypted)
    try:
        os.chmod(staged, 0o600)
    except OSError:
        pass
    try:
        reloaded = serialization.load_pem_private_key(staged.read_bytes(), password=passphrase)
        if reloaded.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ) != public_bytes:
            raise SystemExit("the staged key derives a different public key; refusing to replace")
        # Final gate: the packaged app verifies manifests against the literal in
        # core/release_integrity.py, so a mismatch here must stop the swap.
        assert_key_matches_embedded(repo_root, reloaded)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise

    os.replace(staged, key_path)
    (key_path.with_name(key_path.stem + "-public.pem")).write_bytes(public_bytes)

    print(f"encrypted in place: {key_path}")
    print(f"public key:         {key_path.with_name(key_path.stem + '-public.pem')}")
    print()
    print("The public half did not change, so core/release_integrity.py needs no edit")
    print("and the already-built launcher still verifies what you sign with it.")
    print()
    print(f"Next: set {PASSWORD_ENV} and run finalize_sprotect_release.bat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
