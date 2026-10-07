import subprocess
import sys
from pathlib import Path

import pytest

import main_nuitka_debug


ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_bootstrap_uses_development_cores_when_frozen():
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; sys.frozen=True; "
            "from main_nuitka_debug import install_development_cores; "
            "install_development_cores(); "
            "from engine import dev_core, native_core; "
            "assert native_core.core is dev_core; "
            "assert all(hasattr(dev_core,n) for n in native_core._REQUIRED); "
            "from modes.shipinhao import heimao_luoyue_core, mode_heimao_luoyue_worker; "
            "assert mode_heimao_luoyue_worker.filter_graph is heimao_luoyue_core.filter_graph",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_protected_loader_still_rejects_development_fallback_when_frozen():
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys,types; sys.frozen=True; "
            "sys.modules['app._flowcut_core']=types.ModuleType('app._flowcut_core'); "
            "import engine.native_core",
        ],
        cwd=ROOT,
        capture_output=True,
    )
    assert result.returncode != 0
    assert b"RuntimeError" in result.stderr


def test_startup_error_is_saved_and_not_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "diagnostic.exe")])
    monkeypatch.chdir(tmp_path)

    def fail():
        raise RuntimeError("diagnostic startup failure")

    monkeypatch.setattr(main_nuitka_debug, "install_development_cores", fail)
    with pytest.raises(RuntimeError, match="diagnostic startup failure"):
        main_nuitka_debug.main()
    logs = list((tmp_path / "logs").glob("diagnostic_*.log"))
    assert len(logs) == 1
    assert "RuntimeError: diagnostic startup failure" in logs[0].read_text(encoding="utf-8")
