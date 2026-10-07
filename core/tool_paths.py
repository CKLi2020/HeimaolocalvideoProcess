"""Capture output validation using the tool root supplied by the application."""

from pathlib import Path
from tempfile import NamedTemporaryFile


def prepare_capture_directory(tool_root: str, output_dir: str) -> Path:
    if not tool_root or not Path(tool_root).is_absolute():
        raise ValueError("Capture requires an absolute application tool root")
    root = Path(tool_root).resolve(strict=True)
    capture = (root / "capture").resolve()
    if not capture.is_relative_to(root):
        raise ValueError("Capture directory resolves outside the application tool root")
    requested = Path(output_dir)
    output = (requested if requested.is_absolute() else root / requested).resolve()
    if not output.is_relative_to(capture):
        raise ValueError(f"Capture output must be inside {capture}: {output}")
    output.mkdir(parents=True, exist_ok=True)
    resolved = output.resolve(strict=True)
    if not resolved.is_relative_to(capture):
        raise ValueError(f"Capture output resolves outside {capture}: {resolved}")
    with NamedTemporaryFile(prefix=".capture-write-check-", dir=resolved) as writable:
        writable.write(b"capture")
        writable.flush()
    return resolved
