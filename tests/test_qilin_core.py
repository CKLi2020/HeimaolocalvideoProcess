"""云麒1004 的随机素材与滤镜计划必须由 native_core 提供。"""

from engine.native_core import core


def test_qilin_pipeline_plan_is_complete_and_seeded():
    first = core.qilin_pipeline_plan(1920, 1080, 1004)
    repeated = core.qilin_pipeline_plan(1920, 1080, 1004)
    different = core.qilin_pipeline_plan(1920, 1080, 1005)

    deterministic_fields = (
        "grid_graph",
        "blend_graph",
        "frame_seek",
        "keyframes",
        "geo_source",
        "rotation_source",
    )
    assert all(first[field] == repeated[field] for field in deterministic_fields)
    assert any(first[field] != different[field] for field in deterministic_fields)
    assert first["geo_source"].count("drawbox=") == 36
    assert first["rotation_source"].count("drawbox=") == 24
    assert "s=198x188" in first["geo_source"]
    assert "xstack=inputs=20" in first["grid_graph"]
    assert "anoisesrc=color=pink" in first["blend_graph"]
    assert "scale=1920:1080" in first["blend_graph"]
    assert first["keyframes"].startswith("0,")


def test_qilin_sps_compatibility_is_provided_by_core():
    assert core.qilin_sps_compat_byte(bytes.fromhex("caf016a040402010")) == 0x08
    assert core.qilin_sps_compat_byte(bytes.fromhex("caf016a040402008")) == 0x08
