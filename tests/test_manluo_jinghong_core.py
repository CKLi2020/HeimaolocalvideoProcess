"""漫落惊鸿的关键参数必须由受保护 Core 统一生成。"""

from engine.native_core import core


def test_manluo_jinghong_plan_is_seeded_and_bounded():
    medium = core.manluo_jinghong_plan("medium", 3.0, 4, 20261006)
    assert medium == core.manluo_jinghong_plan("medium", 3.0, 4, 20261006)
    assert medium != core.manluo_jinghong_plan("heavy", 3.0, 4, 20261006)
    assert medium["noise_indices"]
    assert max(medium["noise_indices"]) < 4
    assert 29.98 <= medium["fps"] <= 30.08
