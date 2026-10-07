from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.tool_paths import prepare_capture_directory
from engine.local_processor import LocalProcessorService
from modes.shipinhao.mode_qixia_mode5 import MODE


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


def test_capture_only_service_reports_outside_capture_and_does_not_run(tmp_path):
    service = LocalProcessorService.__new__(LocalProcessorService)
    service.config = {}
    service._stop = threading.Event()
    logs = []
    done = []
    source = tmp_path / "input.mp4"
    source.touch()
    LocalProcessorService._run(
        service,
        {"use_gpu": False, "tool_root": str(tmp_path), "output_dir": str(tmp_path / "outside")},
        SimpleNamespace(capture_output=True), [source], [], logs.append, lambda _value: None,
        lambda *result: done.append(result),
    )
    assert done[0][:3] == (0, 1, 1)
    assert any("Capture output must be inside" in line for line in logs)
    assert not (tmp_path / "outside").exists()


def test_qixia_service_uses_user_selected_folder(tmp_path, monkeypatch):
    import engine.local_processor as local_processor

    service = LocalProcessorService.__new__(LocalProcessorService)
    service.config = {}
    service._stop = threading.Event()
    source = tmp_path / "input.mp4"
    source.touch()
    selected = tmp_path / "user-selected" / "videos"
    paths = []
    done = []
    monkeypatch.setattr(local_processor, "probe_duration", lambda *_args: 1.0)
    monkeypatch.setattr(local_processor, "verify_output", lambda *_args, **_kwargs: (True, "ok"))

    def run_commands(_state, _mode, _source, _aux, base, *_args):
        paths.append(Path(base + ".mp4"))
        paths[-1].write_bytes(b"test-output")
        return 0, False

    monkeypatch.setattr(service, "_run_commands", run_commands)
    monkeypatch.setattr(MODE, "finalize_render", lambda *_args: None)
    LocalProcessorService._run(
        service, {"use_gpu": False, "output_dir": str(selected)}, MODE,
        [source], [], lambda _line: None, lambda _value: None,
        lambda *result: done.append(result),
    )
    assert done[0][:3] == (1, 0, 1)
    assert paths[0].parent == selected
    assert len(list(selected.glob("*.mp4"))) == 1
    assert not (tmp_path / "capture").exists()
