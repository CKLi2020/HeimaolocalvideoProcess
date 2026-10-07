from pathlib import Path
from unittest.mock import patch

import pytest

from core.tool_paths import prepare_capture_directory


def test_capture_is_relative_to_tool_not_working_directory(tmp_path, monkeypatch):
    root = tmp_path / "tool"
    root.mkdir()
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    result = prepare_capture_directory(str(root), "capture/task")
    assert result == root / "capture" / "task"
    assert result.is_dir()
    assert not list(result.iterdir())
    assert not (cwd / "capture").exists()


def test_two_tools_have_isolated_capture_directories(tmp_path):
    for name in ("source", "heimao"):
        root = tmp_path / name
        root.mkdir()
        assert prepare_capture_directory(str(root), str(root / "capture")) == root / "capture"


@pytest.mark.parametrize("output", ["output", "capture/../../outside"])
def test_capture_rejects_output_outside_tree(tmp_path, output):
    with pytest.raises(ValueError, match="Capture output must be inside"):
        prepare_capture_directory(str(tmp_path), output)
    assert not (tmp_path / "output").exists()


def test_capture_requires_application_root():
    with pytest.raises(ValueError, match="absolute application tool root"):
        prepare_capture_directory("", "capture")


def test_capture_reports_creation_and_write_errors(tmp_path):
    with patch.object(Path, "mkdir", side_effect=PermissionError("creation denied")):
        with pytest.raises(PermissionError, match="creation denied"):
            prepare_capture_directory(str(tmp_path), "capture")
    with patch("core.tool_paths.NamedTemporaryFile", side_effect=PermissionError("write denied")):
        with pytest.raises(PermissionError, match="write denied"):
            prepare_capture_directory(str(tmp_path), "capture")
