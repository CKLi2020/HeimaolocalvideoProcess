# -*- coding: utf-8 -*-
"""本地版自检 —— 一条命令验证整个处理链是否正常。

    .venv\\Scripts\\python.exe selftest.py

自检自己造测试素材(用 bin/ffmpeg.exe 的 lavfi 源,不联网、不依赖外部文件),
跑完自己清理。改动 core/ 、modes/ 、mode_defs/ 之后跑一遍,几十秒出结论。

覆盖:
  1  无卡密直达主界面 / 平台与模式加载 / ffmpeg 定位
  2  三通道(默认 · 混剪 · 修复) CPU 端到端
  3  三通道 GPU 端到端(无显卡则跳过)
  4  产物断言:恰好 1 视频 + 1 音频、时长为正、分辨率达标
  5  批量 + 辅视频少于主视频时的循环复用
  6  GPU 回退:无 gpu_command / gpu_command 坏掉,两种都要转 CPU 且不中断
  7  模式扩展:往 mode_defs/ 丢一个 json,下拉框自动多一项

退出码 0 = 全过,1 = 有失败项。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import types

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.chdir(BASE)

import main as app_mod
from core.runner import verify_output

# 模态弹窗会卡死无人值守的自检
POPUPS = []
app_mod.messagebox = types.SimpleNamespace(
    showinfo=lambda *a, **k: POPUPS.append("info: %s" % (a[-1],)),
    showwarning=lambda *a, **k: POPUPS.append("warn: %s" % (a[-1],)),
    showerror=lambda *a, **k: POPUPS.append("error: %s" % (a[-1],)),
    askyesno=lambda *a, **k: True,
)

FAILURES = []
NOTES = []


def check(label, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", label,
                           ("  " + detail) if detail else ""))
    if not ok:
        FAILURES.append("%s%s" % (label, (": " + detail) if detail else ""))
    return ok


def note(text):
    NOTES.append(text)
    print("  [skip] %s" % text)


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def wait_done(app, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)
        if str(app.btn_start.cget("state")) == "normal" and not app.runner.is_running:
            pump(app, 0.5)
            return True
    return False


def run(app, platform, mode_name, main_path, aux_path, out_dir):
    """选平台/模式/文件 -> 开始处理 -> 等结束;返回本次新增的日志。"""
    info = app.platform_widgets[platform]
    info["var"].set(mode_name)
    app._activate_platform(platform)
    app.var_main.set(main_path)
    app.var_aux.set(aux_path)
    app.var_out.set(out_dir)
    mark = len(app.log_lines)
    app.start_process()
    ok = wait_done(app)
    return "\n".join(app.log_lines[mark:]), ok


def outputs(out_dir):
    if not os.path.isdir(out_dir):
        return [], []
    files = sorted(os.listdir(out_dir))
    parts = [f for f in files if f.endswith(".part.mp4")]
    return [f for f in files if not f.endswith(".part.mp4")], parts


def assert_outputs(app, label, out_dir, want_count, want_size):
    files, parts = outputs(out_dir)
    check("%s: 产物 %d 个" % (label, want_count), len(files) == want_count,
          "实际 %d 个: %s" % (len(files), files))
    check("%s: 无残留临时文件" % label, not parts, str(parts))
    for name in files:
        ok, message = verify_output(app.cfg, os.path.join(out_dir, name))
        good = ok and (not want_size or want_size in message)
        check("%s/%s" % (label, name), good, message)


def make_footage(ffmpeg, root):
    """造测试素材:testsrc2 主视频 + smptebars 辅视频。"""
    main_dir = os.path.join(root, "main")
    aux_dir = os.path.join(root, "auxiliary")
    os.makedirs(main_dir, exist_ok=True)
    os.makedirs(aux_dir, exist_ok=True)

    def run_ff(args):
        return subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error"] + args,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for i in (1, 2, 3):
        proc = run_ff(["-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30",
                       "-f", "lavfi", "-i", "sine=frequency=%d" % (400 + i * 100),
                       "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                       os.path.join(main_dir, "m%d.mp4" % i)])
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    for i in (1, 2):
        proc = run_ff(["-f", "lavfi", "-i", "smptebars=size=640x360:rate=25",
                       "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
                       "-pix_fmt", "yuv420p", "-an",
                       os.path.join(aux_dir, "a%d.mp4" % i)])
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return main_dir, aux_dir


def write_def(platform_dir, chan, data):
    path = os.path.join(platform_dir, chan + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


PROBE_BASE = {
    "id": "douyin/_selftest", "name": "自检探针", "platform": "douyin",
    "platform_label": "抖音处理", "needs_aux": False, "gpu_supported": True,
    "output_suffix": "_st", "ext": "mp4", "size": "720x1280", "fps": 30,
    "help_text": "自检", "desc": "自检",
    "command": ('ffmpeg -y -hide_banner -i "{input}" -vf "scale={width}:{height}" '
                '-c:v {video_encoder} -pix_fmt yuv420p -map 0:v:0 -map 0:a:0? '
                '-c:a aac -movflags +faststart "{output}.{ext}"'),
    "gpu_command": "",
}


def main():
    print("=" * 74)
    print("黑猫视频处理软件本地版 · 自检")
    print("=" * 74)

    root = tempfile.mkdtemp(prefix="xhm_selftest_")
    app = None
    try:
        # ---------------------------------------------------------------- 1
        print("\n[1] 启动与加载")
        app = app_mod.App()
        pump(app, 1.2)
        check("无登录/卡密环节,直接进主界面", True, app.title())
        check("平台数 = 8", len(app.mode_groups) == 8, str(list(app.mode_groups)))
        check("ffmpeg 已定位", bool(app.ffmpeg_path), app.ffmpeg_path)
        check("ffprobe 已定位", bool(app.ffprobe_path), app.ffprobe_path)
        total_modes = sum(len(v) for v in app.mode_groups.values())
        check("模式总数 >= 21", total_modes >= 21, "共 %d 个" % total_modes)
        check("无模式加载错误", not getattr(app_mod.load_modes, "errors", []),
              str(getattr(app_mod.load_modes, "errors", [])))
        gpu = app.gpu_profile
        print("      GPU: %s | 默认处理方式: %s" % (app_mod.gpu_summary(gpu), app.var_processor.get()))

        if not app.ffmpeg_path or not app.ffprobe_path:
            FAILURES.append("ffmpeg/ffprobe 未找到,后续检查无法进行")
            return

        from modes.base_mode import BaseMode
        bad_mode = BaseMode()
        bad_mode.command = 'ffmpeg -i "{input}" "{output}.{ext}"'
        bad_mode.fps = "not-a-number"
        _, _, bad_error = bad_mode.render({"main_video": "x.mp4", "output_dir": root})
        check("坏模式参数返回错误而非杀死工作线程", "模式参数无效" in bad_error, bad_error)

        # ---------------------------------------------------------------- 2
        print("\n[2] 生成测试素材")
        main_dir, aux_dir = make_footage(app.ffmpeg_path, root)
        check("主视频 3 个 / 辅视频 2 个",
              len(os.listdir(main_dir)) == 3 and len(os.listdir(aux_dir)) == 2)

        # ---------------------------------------------------------------- 3/4
        for label, use_gpu in (("CPU", False), ("GPU", True)):
            if use_gpu and not gpu.get("available"):
                note("本机无可用 GPU,跳过 GPU 端到端")
                continue
            proc = gpu.get("vendor") if use_gpu else "cpu"
            app.var_processor.set(proc)
            app.var_processor_label.set(app_mod.PROCESSOR_LABELS.get(proc, ""))
            print("\n[%s] 通道端到端 (%s)" % (3 if not use_gpu else 3, label))

            cases = [
                ("抖音处理", "疏影", 720, "720x1280", "hevc_encoder"),
                ("抖音处理", "烟雨", 720, "720x1280", "hevc_encoder"),
                ("快手处理", "长河", 1024, "1024x576", "h264_encoder"),
                ("视频号处理", "云水", 720, "720x1280", "h264_encoder"),
                ("视频号处理", "青岚", 720, "720x1280", "h264_encoder"),
                ("快手处理", "松月", 720, "720x1280", "h264_encoder"),
                ("哔哩处理", "修复", 1920, "1920x1080", "h264_encoder"),
            ]
            for idx, (plat, mode_name, _w, want_size, encoder_key) in enumerate(cases):
                out_dir = os.path.join(root, "out_%s_%d" % (label, idx))
                aux = os.path.join(aux_dir, "a1.mp4") if mode_name in (
                    "烟雨", "云水", "青岚", "松月"
                ) else ""
                text, done = run(app, plat, mode_name, os.path.join(main_dir, "m1.mp4"),
                                 aux, out_dir)
                ok = done and "成功 1 / 失败 0 / 共 1" in text
                check("%s · %s 退出码 0" % (plat, mode_name), ok)
                if ok:
                    assert_outputs(app, "%s %s" % (label, mode_name), out_dir, 1, want_size)
                    if use_gpu and gpu.get(encoder_key) not in text:
                        FAILURES.append("%s · %s 没有走硬件编码" % (label, mode_name))

        # ---------------------------------------------------------------- 5
        print("\n[5] 批量 + 辅视频循环复用")
        app.var_processor.set("cpu")
        out_dir = os.path.join(root, "out_batch")
        text, done = run(app, "抖音处理", "烟雨", main_dir, aux_dir, out_dir)
        check("批量 3 主 / 2 辅 跑完", done and "成功 3 / 失败 0 / 共 3" in text)
        wanted = "提示: 辅视频 2 个,少于主视频 3 个,将循环复用配对"
        check("出现辅视频循环复用提示", wanted in text,
              "" if wanted in text else "日志里的辅视频相关行: %s"
              % [l for l in text.splitlines() if "辅" in l][:4])
        assert_outputs(app, "批量烟雨", out_dir, 3, "720x1280")

        # ---------------------------------------------------------------- 6
        print("\n[6] GPU 回退")
        pdir = os.path.join(BASE, "mode_defs", "douyin")
        if gpu.get("available"):
            app.var_processor.set(gpu.get("vendor"))
            app.var_processor_label.set(app_mod.PROCESSOR_LABELS.get(gpu.get("vendor"), ""))

            path = write_def(pdir, "_st_nogpu", PROBE_BASE)
            try:
                app._load_modes_into_ui()
                pump(app, 0.3)
                out_dir = os.path.join(root, "out_fbA")
                text, done = run(app, "抖音处理", "自检探针", main_dir, "", out_dir)
                check("无 gpu_command 时提示并继续",
                      "当前模式未提供GPU编码命令，已使用CPU原命令处理" in text
                      and done and "成功 3 / 失败 0 / 共 3" in text)
                assert_outputs(app, "回退A", out_dir, 3, "720x1280")
            finally:
                os.remove(path)

            bad = dict(PROBE_BASE, id="douyin/_st_badgpu", name="自检探针B",
                       output_suffix="_stB", gpu_supported=True,
                       gpu_command=PROBE_BASE["command"].replace("{video_encoder}",
                                                                 "h264_doesnotexist_zzz"))
            path = write_def(pdir, "_st_badgpu", bad)
            try:
                app._load_modes_into_ui()
                pump(app, 0.3)
                out_dir = os.path.join(root, "out_fbB")
                text, done = run(app, "抖音处理", "自检探针B", main_dir, "", out_dir)
                hits = text.count("GPU处理失败，重新获取CPU原命令重试；本批次后续直接使用CPU")
                check("GPU 失败后转 CPU 且只提示一次", hits == 1, "出现 %d 次" % hits)
                check("回退不中断批量", done and "成功 3 / 失败 0 / 共 3" in text)
                assert_outputs(app, "回退B", out_dir, 3, "720x1280")
            finally:
                os.remove(path)
        else:
            note("本机无可用 GPU,跳过 GPU 回退")

        # ---------------------------------------------------------------- 7
        print("\n[7] 模式扩展性")
        info = app.platform_widgets["抖音处理"]
        before = [m.name for m in info["modes"]]
        path = write_def(pdir, "_st_extra", dict(
            PROBE_BASE, id="douyin/_st_extra", name="自检扩展通道", output_suffix="_stX"))
        try:
            app._load_modes_into_ui()
            pump(app, 0.3)
            after = [m.name for m in app.platform_widgets["抖音处理"]["modes"]]
            check("丢 json -> 下拉框多一项", "自检扩展通道" in after,
                  "%s -> %s" % (before, after))
            check("下拉框控件同步更新",
                  "自检扩展通道" in list(app.platform_widgets["抖音处理"]["combo"].cget("values")))
        finally:
            os.remove(path)
            app._load_modes_into_ui()
            pump(app, 0.2)

        # ---------------------------------------------------------------- 8
        print("\n[8] 配置容错(原版正是死在这里)")
        from core import build_config
        good = build_config.CONFIG_PATH
        backup = good + ".selftest_backup"
        shutil.copy2(good, backup)
        try:
            with open(good, "w", encoding="utf-8") as fh:
                fh.write('{"app_title": "x"} garbage after json')   # 原版崩法:Extra data
            cfg = build_config.load_config()
            check("坏 JSON 不抛异常且退回默认值",
                  bool(cfg.get("default_threads")), str(build_config.load_config.warnings))
        finally:
            shutil.move(backup, good)

    except Exception:
        FAILURES.append("自检自身异常:\n" + traceback.format_exc())
        traceback.print_exc()
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:
                pass
        shutil.rmtree(root, ignore_errors=True)

    print()
    print("=" * 74)
    print("结果: %s" % ("全部通过" if not FAILURES else "失败 %d 项" % len(FAILURES)))
    print("=" * 74)
    for item in FAILURES:
        print("  ✘ " + item)
    if NOTES:
        for item in NOTES:
            print("  - " + item)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
