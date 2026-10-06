"""Functional checks executed inside the packaged launcher."""

from concurrent.futures import ThreadPoolExecutor


def check_host_gates(core, swap, *, require_enabled=False):
    statuses = {}
    for name, module in (("flowcut", core), ("random_frame_swap", swap)):
        status = module.host_gate_status()
        statuses[name] = status
        if not status["allowed"]:
            raise RuntimeError(f"{name}: native core host check failed (FCG1 / 0x46434731)")
        if require_enabled and not status["enabled"]:
            raise RuntimeError(f"{name}: release native core host gate is disabled")
    return statuses


def exercise_algorithms(core, swap):
    def check(condition, name):
        if not condition:
            raise RuntimeError(f"Native core self-test failed: {name}")

    check(bool(core.mask_alpha(1080, 1920, 20, .05, 0)), "mask_alpha")
    check(core.butterfly_plan(60, 2)["main_frames"] == 1800, "butterfly_plan")
    check("drawbox=" in core.window_matte_chain(1080, 1920, 50, 50, 80, 100, 200),
          "window_matte_chain")
    check(len(core.concat_filter_segment(0, 1, False, 1080, 1920, 30)) == 2,
          "concat_filter_segment")
    check(.9 < core.playback_rate(.93, 1.15, 1) < 1.2, "playback_rate")
    check(len(core.filter_segments(5, 1)) == 5, "filter_segments")
    check("eq=" in core.color_adjustments_filter("x", 10, 0, 0, 0, "", 100)[0],
          "color_adjustments_filter")
    check(any("afftdn=" in item for item in core.mild_voice_filters("1:a", 25, 1)[0]),
          "mild_voice_filters")
    plan = core.qilin_pipeline_plan(1920, 1080, 1004)
    check(plan["geo_source"].count("drawbox=") == 36 and
          plan["rotation_source"].count("drawbox=") == 24 and
          "xstack=inputs=20" in plan["grid_graph"] and
          "anoisesrc=color=pink" in plan["blend_graph"], "qilin_pipeline_plan")
    for value in ("caf016a040402010", "caf016a040402008"):
        check(core.qilin_sps_compat_byte(bytes.fromhex(value)) == 8,
              "qilin_sps_compat_byte")
    check(core.liuying_video_filter(1003).count("perspective=") == 1 and
          core.liuying_video_filter(1003, True).count("perspective=") == 2,
          "liuying_video_filter")
    check(core.liuying_perspective_filter(1003).startswith("perspective="),
          "liuying_perspective_filter")
    check(core.liuying_flash_filter(1003).startswith("perspective="),
          "liuying_flash_filter")
    check(core.liuying_base_filter().startswith("fps=60"), "liuying_base_filter")
    check(core.liuying_seed(1003, 2) == 210461, "liuying_seed")
    check(core.motianxinglun_pipeline_plan(1.25)["image_fps"] == "120",
          "motianxinglun_pipeline_plan")
    check("all_mode=screen" in core.tianbaixinglun_pipeline_plan(1.25)["blend_filter"],
          "tianbaixinglun_pipeline_plan")
    plan = core.manluo_jinghong_plan("medium", 3.0, 4, 20261006)
    check(plan["fps"] > 0 and plan["noise_indices"] and max(plan["noise_indices"]) < 4,
          "manluo_jinghong_plan")
    graph = swap.filter_graph()
    check(graph.startswith("[0:v:0]fps=30,scale=720:1280") and
          graph.endswith("setpts=N[vout]"), "filter_graph")
    check(sorted(swap.shuffled_order(20, 1)) == list(range(20)) and
          swap.shuffled_order(20, 1) == swap.shuffled_order(20, 1), "shuffled_order")
    check(swap.special_offsets([1000, 1000, 1000], [0, 10, 20]) == [0, 498, 996],
          "special_offsets")


def run_self_test(core, swap):
    statuses = check_host_gates(core, swap, require_enabled=True)
    exercise_algorithms(core, swap)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(exercise_algorithms, core, swap) for _ in range(4)]
        for future in futures:
            future.result()
    return statuses
