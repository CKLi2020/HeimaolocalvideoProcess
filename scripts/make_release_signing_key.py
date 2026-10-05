"""Generate the Ed25519 keypair that signs the release manifest.

This key is the root of release trust: whoever holds the private half can sign a
manifest for any build, and every installed copy of the product will accept it.
So it is generated once, with a passphrase, and kept off the repository.

Usage (from the repo root):

    python scripts\\make_release_signing_key.py --out "%USERPROFILE%\\.blackcat-release\\manifest-private.pem"

The passphrase is read from BLACKCAT_RELEASE_KEY_PASSWORD, or prompted for if
that is unset. It must not be blank: an unencrypted private key is exactly the
problem this script exists to avoid.

After it runs, paste the printed public key into core/release_integrity.py and
rebuild: an already-released launcher carries the *old* public key compiled in,
so rotating the signing key also requires reissuing the launcher.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

PASSWORD_ENV = "BLACKCAT_RELEASE_KEY_PASSWORD"


def read_passphrase() -> str:
    value = os.environ.get(PASSWORD_ENV)
    if value is not None:
        if not value:
            raise SystemExit(f"{PASSWORD_ENV} is set but empty; unset it to be prompted instead")
        return value
    if not sys.stdin.isatty():
        raise SystemExit(f"set {PASSWORD_ENV} to read the passphrase without a terminal")
    first = getpass.getpass("Passphrase for the new release signing key: ")
    if not first:
        raise SystemExit("the passphrase must not be blank")
    if first != getpass.getpass("Repeat it: "):
        raise SystemExit("the passphrases did not match")
    return first


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="where to write the encrypted private key")
    parser.add_argument("--force", action="store_true", help="overwrite an existing private key")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out = Path(args.out).expanduser().resolve()
    if out == repo_root or repo_root in out.parents:
        raise SystemExit(f"refusing to write the signing key inside the repository: {out}")
    if out.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite an existing key (pass --force): {out}")

    key = ed25519.Ed25519PrivateKey.generate()
    passphrase = read_passphrase().encode("utf-8")

    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(private_bytes)
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass

    public_path = out.with_name(out.stem + "-public.pem")
    public_path.write_bytes(public_bytes)

    print(f"private key (encrypted, keep offline): {out}")
    print(f"public key:                            {public_path}")
    print()
    print("Replace the _PUBLIC_KEY literal in core/release_integrity.py with this block:")
    print()
    print('_PUBLIC_KEY = b"""' + public_bytes.decode("ascii") + '"""')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
