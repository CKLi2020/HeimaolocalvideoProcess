import base64
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows release build")


def copy_assets(source, release):
    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"

    command = (
        "$ErrorActionPreference='Stop'; "
        f". {quote(ROOT / 'scripts' / 'release_assets.ps1')}; "
        f"Copy-ReleaseAssets {quote(source)} {quote(release)}"
    )
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_missing_optional_assets_do_not_block_build(tmp_path):
    source, release = tmp_path / "source", tmp_path / "release"
    (source / "resources").mkdir(parents=True)
    (source / "resources" / "required.txt").write_text("required", encoding="utf-8")
    result = copy_assets(source, release)
    assert result.returncode == 0, result.stderr
    assert (release / "resources" / "required.txt").read_text() == "required"
    for name in ("贴纸", "配置文件"):
        assert (release / name).is_dir()
        assert list((release / name).iterdir()) == []
    assert b"Optional release assets not found" in result.stderr + result.stdout


def test_existing_optional_assets_are_copied(tmp_path):
    source, release = tmp_path / "source", tmp_path / "release"
    (source / "resources").mkdir(parents=True)
    for name in ("贴纸", "配置文件"):
        (source / name).mkdir()
        (source / name / "asset.txt").write_text("existing", encoding="utf-8")
    result = copy_assets(source, release)
    assert result.returncode == 0, result.stderr
    for name in ("贴纸", "配置文件"):
        assert (release / name / "asset.txt").read_text() == "existing"


def test_missing_required_resources_still_fails(tmp_path):
    source, release = tmp_path / "source", tmp_path / "release"
    source.mkdir()
    result = copy_assets(source, release)
    assert result.returncode != 0
    assert b"Required release directory not found" in result.stderr
    assert not release.exists()
