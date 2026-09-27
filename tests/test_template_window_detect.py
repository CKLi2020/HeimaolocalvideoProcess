"""模板窗口探测的回归测试。

钉住两件事：

1. **坐标换算**。这里曾经出过两个同类 bug：探测帧是缩放过的小图，探测坐标
   被直接当成模板原生像素用（清单值整体偏小），以及 drawbox 在 `scale` 之后
   生效、却被喂了原生像素（框画到画面外）。两个 bug 都不会报错，只会静默给错数，
   所以必须用测试钉住。

2. **跨纵横比换算**。模板 9:16、画布更窄时，窗口的宽会超过画布的 100%
   （模板被放大后左右裁掉，模板里 80% 的宽会变成画布的 97%）。这是正确结果，
   不是探测失败，不能在合理性校验里被当成异常刷掉。

用法：python tests\\test_template_window_detect.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import detect_template_windows as dtw  # noqa: E402

NATIVE = (1080, 1920)


def _synthetic_template(path: Path, box_pct) -> None:
    """合成一个模板：花哨背景 + 一块纯灰的“窗口”。

    背景用 testsrc2，保证窗口外的行有明显纹理（行内极差大），
    这样才真正走「行内平坦 + 同色」两个判据，而不是靠颜色蒙对。
    """
    cx, cy, w, h = box_pct
    bw = int(NATIVE[0] * w / 100)
    bh = int(NATIVE[1] * h / 100)
    bx = int(NATIVE[0] * cx / 100) - bw // 2
    by = int(NATIVE[1] * cy / 100) - bh // 2
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=s={NATIVE[0]}x{NATIVE[1]}:r=15:d=3",
         "-vf", f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=0x6e6e6e:t=fill",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def check_coordinate_math() -> int:
    """坐标换算：探测坐标必须能还原到原生像素，而不是直接当原生像素用。"""
    failures = 0
    # 探测帧 (270x480) 相对原生 (1080x1920) 的倍率是 4
    box = (27, 96, 216, 288)
    native_box = dtw.rescale_box(box, NATIVE)
    if native_box != (108, 384, 864, 1152):
        failures += 1
        print(f"  失败 rescale_box -> {native_box}，期望 (108, 384, 864, 1152)")

    # 缩略图空间也一样：drawbox 在 scale 之后生效，坐标必须落在缩略图上
    sheet_box = dtw.rescale_box(box, (200, 356))
    if sheet_box != (20, 71, 160, 214):
        failures += 1
        print(f"  失败 rescale_box(缩略图) -> {sheet_box}，期望 (20, 71, 160, 214)")

    # 模板空间百分比
    local = dtw.to_template_pct(box)
    if (round(local["window_w"]), round(local["window_h"])) != (80, 60):
        failures += 1
        print(f"  失败 to_template_pct -> {local}，期望 80%x60%")

    print(f"  坐标换算：{'通过' if not failures else '失败'}")
    return failures


def check_canvas_conversion() -> int:
    """跨纵横比换算：模板与画布同比例时 1:1，不同比例时按 increase+crop 换算。"""
    failures = 0
    box = (27, 96, 216, 288)          # 模板空间 80%x60% @ (50,50)

    same = dtw.to_canvas_pct(box, NATIVE, (1080, 1920))
    if same != {"window_center_x": 50, "window_center_y": 50,
                "window_w": 80, "window_h": 60}:
        failures += 1
        print(f"  失败 同比例画布 -> {same}，期望 80%x60% @ (50,50)")

    # 画布 1080x2338 比模板更窄：放大 2338/1920 后左右各裁掉约 117px，
    # 于是模板里 80% 的宽变成画布的约 97%，中心仍在 50%。
    narrow = dtw.to_canvas_pct(box, NATIVE, (1080, 2338))
    if (narrow["window_center_x"], narrow["window_center_y"]) != (50, 50):
        failures += 1
        print(f"  失败 窄画布中心 -> {narrow}")
    if abs(narrow["window_w"] - 97) > 1:
        failures += 1
        print(f"  失败 窄画布宽 -> {narrow['window_w']}%，期望约 97%")
    if abs(narrow["window_h"] - 60) > 1:
        failures += 1
        print(f"  失败 窄画布高 -> {narrow['window_h']}%，期望约 60%")

    # 窗口宽超过画布 100% 是合法的：画布比模板窄时，窗口两侧本来就在画布之外。
    # 这类值绝不能在合理性校验里被当成探测失败刷掉。80% 的模板宽只能换到 97%
    # 画布宽，所以要 >82% 才会越界 —— 用一个 95% 的窗口来钉这一点。
    # 注意 to_canvas_pct 收的是探测坐标，内部自己会还原到原生像素
    wide = dtw.to_canvas_pct((7, 96, 256, 288), NATIVE, (1080, 2338))
    if wide["window_w"] <= 100:
        failures += 1
        print(f"  失败 95% 模板宽应换算成 >100% 画布宽，实得 {wide['window_w']}%")
    if wide["window_w"] != 115:
        failures += 1
        print(f"  失败 95% 模板宽 -> {wide['window_w']}%，期望 115%")

    print(f"  跨纵横比换算：{'通过' if not failures else '失败'}")
    return failures


def check_detection(folder: Path) -> int:
    """合成模板上跑探测：窗口位置/尺寸应能被还原出来。"""
    failures = 0
    cases = [
        ("标准窗口", (50, 50, 80, 60), (1080, 1920), (50, 50, 80, 60)),
        ("窄画布", (50, 50, 80, 60), (1080, 2338), (50, 50, 97, 60)),
        ("偏上窗口", (50, 40, 70, 50), (1080, 1920), (50, 40, 70, 50)),
    ]
    for index, (name, box_pct, canvas, expect) in enumerate(cases):
        clip = folder / f"合成{index}.mp4"
        _synthetic_template(clip, box_pct)

        box = dtw.detect_window(clip)
        if box is None:
            failures += 1
            print(f"  失败 {name}: 探测失败（合成素材应当可判）")
            continue

        values = dtw.to_canvas_pct(box, NATIVE, canvas)
        got = (values["window_center_x"], values["window_center_y"],
               values["window_w"], values["window_h"])
        # 探测帧只有 270x480，再叠加圆角与压缩噪声，容差给 3 个百分点
        bad = [abs(got[i] - expect[i]) for i in range(4)]
        if max(bad) > 3:
            failures += 1
            print(f"  失败 {name}: 得到 {got}，期望 {expect}（差 {bad}）")

    print(f"  合成素材探测：{'通过' if not failures else '失败'}")
    return failures


def demo() -> None:
    print("== 模板窗口探测 ==")
    failures = 0
    failures += check_coordinate_math()
    failures += check_canvas_conversion()
    with TemporaryDirectory() as tmp:
        failures += check_detection(Path(tmp))
    assert failures == 0, f"{failures} 项失败"
    print("template window detect test: OK")


if __name__ == "__main__":
    demo()
