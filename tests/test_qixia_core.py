import itertools

import pytest

from engine import dev_core
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
