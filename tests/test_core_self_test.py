from types import SimpleNamespace
import json
import sys

import pytest

from engine import dev_core
from engine.core_self_test import check_host_gates, exercise_algorithms, run_self_test
from modes.shipinhao import heimao_luoyue_core


def test_all_algorithm_checks_match_development_cores():
    exercise_algorithms(dev_core, heimao_luoyue_core)


def test_release_checks_include_background_calls(monkeypatch):
    status = lambda: {"enabled": True, "allowed": True}
    monkeypatch.setattr(dev_core, "host_gate_status", status, raising=False)
    monkeypatch.setattr(heimao_luoyue_core, "host_gate_status", status, raising=False)
    assert run_self_test(dev_core, heimao_luoyue_core) == {
        "flowcut": status(), "random_frame_swap": status(),
    }


@pytest.mark.parametrize("enabled,allowed,message", [
    (True, False, "FCG1"),
    (False, True, "disabled"),
])
def test_release_gate_failure_is_explicit(enabled, allowed, message):
    module = SimpleNamespace(host_gate_status=lambda: {"enabled": enabled, "allowed": allowed})
    with pytest.raises(RuntimeError, match=message):
        check_host_gates(module, module, require_enabled=True)


def test_failed_algorithm_result_is_rejected(monkeypatch):
    monkeypatch.setattr(dev_core, "liuying_seed", lambda *args: 0)
    with pytest.raises(RuntimeError, match="liuying_seed"):
        exercise_algorithms(dev_core, heimao_luoyue_core)


@pytest.mark.parametrize("allowed,expected_exit", [(True, 0), (False, 1)])
def test_launcher_self_test_writes_report_without_user_configuration(
    tmp_path, monkeypatch, allowed, expected_exit,
):
    import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "launcher.exe"), "--native-core-self-test"])
    import main as entry

    monkeypatch.setattr(entry, "ROOT", tmp_path)
    status = lambda: {"enabled": True, "allowed": allowed}
    monkeypatch.setattr(dev_core, "host_gate_status", status, raising=False)
    monkeypatch.setattr(heimao_luoyue_core, "host_gate_status", status, raising=False)
    monkeypatch.setattr(app, "_flowcut_core", dev_core, raising=False)
    monkeypatch.setattr(app, "_random_frame_swap_core", heimao_luoyue_core, raising=False)
    with pytest.raises(SystemExit) as error:
        entry.main()
    assert error.value.code == expected_exit
    report = json.loads((tmp_path / "native-core-self-test.json").read_text(encoding="utf-8"))
    assert report["passed"] is allowed
    if not allowed:
        assert "FCG1" in report["error"]
    assert not (tmp_path / "config.json").exists()
