import itertools
from pathlib import Path
import runpy
from types import ModuleType

import pytest

from engine import dev_core
import engine.native_core as loader
from engine.native_core import core


@pytest.mark.parametrize("daoli,lasong,ronghe", tuple(itertools.product([False, True], repeat=3)))
@pytest.mark.parametrize("opacity", [0, 25, 50, 100])
def test_qixia_core_plan_is_equivalent(daoli, lasong, ronghe, opacity):
    plan = core.qixia_pipeline_plan(daoli, lasong, ronghe, opacity)
    assert plan == dev_core.qixia_pipeline_plan(daoli, lasong, ronghe, opacity)
    assert ("blend=" in plan["filter_complex"]) is ronghe
    assert ("vflip" in plan["filter_complex"]) is daoli
    assert ("colorprim=bt709" in plan["x264_params"]) is lasong
    assert "b-adapt=0" in plan["x264_params"] and "ref=4" in plan["x264_params"]


@pytest.mark.parametrize("opacity", [-1, 101, True, 50.1, "50", None])
def test_qixia_core_rejects_invalid_opacity(opacity):
    with pytest.raises(ValueError, match="opacity"):
        core.qixia_pipeline_plan(opacity=opacity)


def test_source_uses_dev_core_when_release_core_denies_python_host(monkeypatch):
    import app

    protected = ModuleType("app._flowcut_core")
    for name in loader._REQUIRED:
        setattr(protected, name, lambda: None)
    protected.host_gate_status = lambda: {"enabled": True, "allowed": False}
    monkeypatch.setattr(app, "_flowcut_core", protected, raising=False)
    monkeypatch.delattr("sys.frozen", raising=False)
    result = runpy.run_path(str(Path(loader.__file__)))
    assert result["core"] is dev_core


def test_release_loader_still_rejects_missing_protected_api(monkeypatch):
    import app

    monkeypatch.setattr(app, "_flowcut_core", ModuleType("incomplete"), raising=False)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    with pytest.raises(RuntimeError, match="原生算法核心"):
        runpy.run_path(str(Path(loader.__file__)))
