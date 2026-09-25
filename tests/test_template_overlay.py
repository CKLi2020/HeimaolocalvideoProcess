"""模板通道测试：窗口几何、清单优先级、向后兼容与端到端画面。

重点钉住五件事：
1. 关掉模板时 overlay 表达式与历史版本**逐字节相同**（老配置零回归）。
2. 打开模板时主视频**不变小**：缩放链与定位表达式都与无模板时一致，
   窗口几何只写进主视频的 alpha。
3. 窗口内外不能反：`[bg][main]overlay` 里 alpha=255 是**主视频可见**，
   所以窗口内要给 255。反了的话画面整个翻过来，必须有用例钉死。
4. 蒙版是几何做法且**满量程**：drawbox 的白落到 gray 帧上只有 235
   （ffmpeg 对 yuv/gray 做有限范围映射），当 alpha 用就只剩 92% 不透明、
   模板会整片透上来一层。所以链上必须有那次二值化；同时不能退回全屏 geq
   （实测慢 4.4 倍）。
5. 端到端：窗口内是主视频、四周是模板。

用法：python tests\\test_template_overlay.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from config import AppConfig  # noqa: E402
from engine.auth import mask_alpha  # noqa: E402
from engine.ffmpeg_builder import build_ffmpeg_command  # noqa: E402
from engine.template_lib import Window, load_library  # noqa: E402
from engine.pipeline import process_batch  # noqa: E402
from test_pipeline_smoke import _assets, _config, _ffmpeg  # noqa: E402

CANVAS = "360x640"
CANVAS_W, CANVAS_H = (int(v) for v in CANVAS.split("x"))

# 主视频源 320x240 经 main_scale=90 后是 288x216，适配画布时居中，
# 帧落在 x36~324 / y212~428。下面取的两个采样点都在帧内，且留足余量。
CENTER = (CANVAS_W // 2, CANVAS_H // 2)     # (180, 320)
LEFT = (60, CANVAS_H // 2)                  # 帧内、居中窗口之外

CORNERS = (("左上", (2, 2)), ("右上", (CANVAS_W - 3, 2)),
           ("左下", (2, CANVAS_H - 3)), ("右下", (CANVAS_W - 3, CANVAS_H - 3)))

BASELINE_OVERLAY = "[bg][main]overlay=(W-w)/2:(H-h)/2:shortest=1[base]"


def _graph(folder: Path, window=None, mask: bool = False) -> str:
    config = _config(folder)
    config.resolution = CANVAS
    config.mask_enabled = mask
    cmd = build_ffmpeg_command(
        config,
        folder / "main" / "main.mp4",
        folder / "bg" / "bg.mp4",
        folder / "out.mp4",
        template_window=window,
    )
    return cmd[cmd.index("-filter_complex") + 1]


def _overlay(folder: Path, window=None) -> str:
    return next(s for s in _graph(folder, window).split(";")
                if s.startswith("[bg][main]overlay"))


def _main_scale(folder: Path, window=None) -> str:
    return next(s for s in _graph(folder, window).split(";")
                if s.startswith("[1:v]"))


def _matte(folder: Path, window=None) -> str:
    """取出窗口几何蒙版的滤镜链。"""
    return next(s for s in _graph(folder, window).split(";")
                if s.startswith("[tpl_geo]"))


def check_backward_compatible(folder: Path) -> int:
    """无模板时必须与历史命令逐字节一致。"""
    failures = 0
    overlay = _overlay(folder, None)
    if overlay != BASELINE_OVERLAY:
        failures += 1
        print(f"  失败 无模板 overlay 变了: {overlay}")
    scale = _main_scale(folder, None)
    if "scale=360:640:force_original_aspect_ratio=decrease" not in scale:
        failures += 1
        print(f"  失败 无模板主视频缩放变了: {scale}")
    # 无模板又没开蒙版时不该给主视频多套一层 alpha
    # （注意：顶/底蒙版层也用了 geq，所以要认 [main_raw] 这个节点）
    if "[main_raw]" in _graph(folder, None):
        failures += 1
        print("  失败 无模板无蒙版时不应生成主视频 alpha")
    print(f"  无模板向后兼容：{'通过' if not failures else '失败'}")
    return failures


def check_window_math(folder: Path) -> int:
    """窗口几何只写进主视频 alpha，主视频自己的缩放与定位不受影响。"""
    failures = 0

    # 1) 主视频的缩放链与「无模板」完全一致 —— 模板不该把主视频变小
    base_scale = _main_scale(folder, None)
    for window in (Window(50, 50, 80, 55, 60), Window(50, 42, 100, 100, 0)):
        scaled = _main_scale(folder, window)
        if scaled.replace("[main_raw]", "[main]") != base_scale:
            failures += 1
            print(f"  失败 {window} 主视频缩放被模板改了: {scaled}")

    # 2) 定位表达式也一样：窗口已经写进 alpha，不再参与定位
    for window in (None, Window(50, 42, 80, 55, 60)):
        overlay = _overlay(folder, window)
        if overlay != BASELINE_OVERLAY:
            failures += 1
            print(f"  失败 {window} overlay={overlay}")

    # 3) 画布 360x640、窗口 80%x55% 居中、羽化 60（按 1080 基准缩放 → 20px）。
    #    窗口在画布上是 x36~324 / y144~496；帧内坐标要减去画布偏移，
    #    但常数项里只留 (画布坐标 - 画布/2)，另一半交给 ffmpeg 的 iw/2 补上。
    #    羽化 20px 用半径为 round((20-1)/2)=10 的单次 boxblur（2r+1=21px 过渡带）。
    matte = _matte(folder, Window(50, 50, 80, 55, 60))
    for term in ("x=iw/2-144", "y=ih/2-176", "w=288", "h=352", "boxblur=10:1"):
        if term not in matte:
            failures += 1
            print(f"  失败 窗口蒙版缺项 {term}: {matte}")
    # ffmpeg 画颜色对 yuv/gray 做有限范围映射，白是 235 不是 255：
    # 少了这次二值化，窗口内就只有 92% 不透明，模板会整片透上来
    if "if(gt(val,128),255,0)" not in matte:
        failures += 1
        print(f"  失败 窗口蒙版没有把 235 拉回 255: {matte}")
    if matte.startswith("[tpl_geo]format=gray,lutyuv=y=0,drawbox=") is False:
        failures += 1
        print(f"  失败 窗口蒙版没有先清空底子再画框: {matte}")
    # 全屏 geq 实测把渲染拖慢到 4.4 倍，别退回去
    if "[main_raw]geq" in _graph(folder, Window(50, 50, 80, 55, 60)):
        failures += 1
        print("  失败 模板模式又用上全屏 geq 了（性能会掉到 4.4 倍）")

    # 4) 窗口给到比画布大：左右边各到帧内 x=-36 / x=396，等于不挖洞
    big = _matte(folder, Window(50, 50, 120, 120, 0))
    if "x=iw/2-216" not in big or "y=ih/2-384" not in big:
        failures += 1
        print(f"  失败 120% 窗口边界算错: {big}")
    # 羽化 0 也不能没有过渡带（boxblur 半径至少 1）
    if "boxblur=1:1" not in big:
        failures += 1
        print(f"  失败 羽化 0 时应退化成最小过渡带: {big}")

    # 5) 用户蒙版与模板窗口同时开：几何蒙版打底，再用 geq 乘上蒙版。
    #    这次 geq 会整块覆写 alpha，必须读回进来的 alpha（alpha(X,Y)），
    #    否则窗口白挖 —— 主视频会被用户蒙版之外的区域也一起切掉。
    combo = _graph(folder, Window(50, 50, 80, 55, 60), mask=True)
    mask_expr = mask_alpha(CANVAS_W, CANVAS_H, _config(folder).mask_feather,
                           _config(folder).mask_margin_tb / 100.0,
                           _config(folder).mask_margin_lr / 100.0)
    if "[tpl_src][tpl_matte]alphamerge[tpl_win]" not in combo:
        failures += 1
        print(f"  失败 模板+蒙版时几何蒙版没打底: {combo}")
    if f"a='{mask_expr}*alpha(X,Y)/255'[main]" not in combo:
        failures += 1
        print(f"  失败 模板+蒙版时没有把窗口 alpha 乘回去: {combo}")
    # 只开蒙版不开模板时，路径必须与历史版本一致
    if f"a='{mask_expr}'[main]" not in _graph(folder, None, mask=True):
        failures += 1
        print("  失败 只开蒙版时不该走模板那条路")

    print(f"  窗口几何：{'通过' if not failures else '失败'}")
    return failures


def check_manifest_precedence(folder: Path) -> int:
    """清单优先级：每模板覆盖 > defaults > config 全局。"""
    failures = 0
    tpl = folder / "模板"
    tpl.mkdir(exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "color=green:s=320x240:r=15:d=1",
            "-pix_fmt", "yuv420p", str(tpl / "a.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "color=green:s=320x240:r=15:d=1",
            "-pix_fmt", "yuv420p", str(tpl / "b.mp4"))
    (tpl / "模板.json").write_text(json.dumps({
        "version": 1,
        "defaults": {"window_center_y": 44, "window_w": 80, "window_feather": 30},
        "templates": [
            {"file": "a.mp4", "window_center_y": 40},
            {"file": "b.mp4", "window_w": 90, "window_h": 60},
            {"file": "缺失.mp4"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    config = _config(folder)
    config.tpl_window_center_x = 50     # 全局
    config.tpl_window_center_y = 50
    config.tpl_window_w = 70
    config.tpl_window_h = 55

    library = load_library(tpl, "模板.json")
    # 清单里不存在的文件被跳过，剩下 2 个
    if len(library.specs) != 2:
        failures += 1
        print(f"  失败 模板数应为 2，实得 {len(library.specs)}")

    windows = {s.path.name: library.resolve(s, config) for s in library.specs}
    # a: center_y 来自自己的覆盖(40)，w 来自 defaults(80)，其余来自全局
    if windows.get("a.mp4") != Window(50, 40, 80, 55, 30):
        failures += 1
        print(f"  失败 a.mp4 窗口 {windows.get('a.mp4')}，期望 Window(50,40,80,55,30)")
    # b: w/h 来自自己的覆盖，center_y 与 feather 来自 defaults
    if windows.get("b.mp4") != Window(50, 44, 90, 60, 30):
        failures += 1
        print(f"  失败 b.mp4 窗口 {windows.get('b.mp4')}，期望 Window(50,44,90,60,30)")

    # 没有清单也要能用：扫描目录 + 全局默认
    bare = load_library(tpl, "不存在的清单.json")
    if len(bare.specs) != 2 or bare.defaults:
        failures += 1
        print(f"  失败 无清单时应扫到 2 个且无 defaults，实得 {len(bare.specs)}")
    if bare.resolve(bare.specs[0], config) != Window(50, 50, 70, 55, 200):
        failures += 1
        print("  失败 无清单时应全部取 config 全局值")

    # 清单损坏：静默退回
    (tpl / "坏.json").write_text("{ 这不是 json", encoding="utf-8")
    broken = load_library(tpl, "坏.json")
    if len(broken.specs) != 2:
        failures += 1
        print("  失败 清单损坏时应退回扫描目录")

    # 窗口尺寸下限被夹住；feather 允许 0（硬边）
    clamped = bare.resolve(
        type(bare.specs[0])(path=bare.specs[0].path,
                            overrides={"window_w": 0, "window_h": 999,
                                       "window_feather": -5}),
        config,
    )
    if (clamped.width, clamped.height, clamped.feather) != (1, 100, 0):
        failures += 1
        print(f"  失败 越界窗口未夹紧: {clamped}")

    print(f"  清单优先级与容错：{'通过' if not failures else '失败'}")
    return failures


def _picks(folder: Path) -> int:
    """随机 / 固定两种选法。"""
    failures = 0
    # 独占一个目录：别用 folder/"模板"，那里面 check_manifest_precedence 已经
    # 放过别的文件了，随机挑中的可能不是这里建的这三张。
    tpl = folder / "选法模板"
    tpl.mkdir(exist_ok=True)
    for name in ("甲.mp4", "乙.mp4", "丙.mp4"):
        _ffmpeg("-f", "lavfi", "-i", "color=green:s=320x240:r=15:d=1",
                "-pix_fmt", "yuv420p", str(tpl / name))
    library = load_library(tpl, "")
    names = {spec.path.name for spec in library.specs}
    if names != {"甲.mp4", "乙.mp4", "丙.mp4"}:
        failures += 1
        print(f"  失败 这个目录应只有这三张模板，实得 {names}")

    # 固定：每次都必须是同一张，连挑 20 次都不许漂
    picked = {library.pick("固定", "乙.mp4").path.name for _ in range(20)}
    if picked != {"乙.mp4"}:
        failures += 1
        print(f"  失败 固定模板应每次都取乙.mp4，实得 {picked}")

    # 随机：整批里应该不止一张（3 选 1 连挑 60 次还全同的概率可忽略）
    random_picks = {library.pick("随机").path.name for _ in range(60)}
    if len(random_picks) < 2:
        failures += 1
        print(f"  失败 随机应能挑到不止一张，实得 {random_picks}")

    # 固定项不在库里（文件被删/改名）：退回随机，不抛错也不返回 None
    fallback = library.pick("固定", "被删掉了.mp4")
    if fallback is None or fallback.path.name not in names:
        failures += 1
        print(f"  失败 固定项缺失时应退回随机，实得 {fallback}")

    # has() 是调用方判断「固定项到底命中没有」的依据
    if not library.has("甲.mp4") or library.has("被删掉了.mp4"):
        failures += 1
        print("  失败 has() 判断不准")

    # 固定但没填名字 → 等同随机（不返回 None）
    if library.pick("固定", "") is None:
        failures += 1
        print("  失败 固定未填名字时应等同随机")

    # 不认识的选法（老配置里的「顺序」）→ 随机
    if library.pick("顺序") is None:
        failures += 1
        print("  失败 不认识的选法应退回随机")

    # 空库：任何选法都是 None
    empty = load_library(folder / "不存在的模板目录", "")
    for order in ("随机", "固定"):
        if empty.pick(order, "甲.mp4") is not None:
            failures += 1
            print(f"  失败 空库 {order} 应返回 None")

    print(f"  随机/固定选择：{'通过' if not failures else '失败'}")
    return failures


def _green_template(folder: Path) -> Path:
    tpl = folder / "模板"
    tpl.mkdir(exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "color=green:s=720x1280:r=15:d=2",
            "-pix_fmt", "yuv420p", str(tpl / "绿模板.mp4"))
    return tpl


def _render(folder: Path, tpl: Path, main: Path = None, **window):
    """按给定窗口跑一次模板批处理，返回取像素的函数（失败返回 None）。

    背景目录故意留空 —— 模板模式下模板即背景，没有背景视频也该能出片。
    """
    config = _config(folder)
    config.background_folder = str(folder / "空背景")
    if main is not None:
        config.main_folder = str(main)
    config.tpl_enabled = True
    config.tpl_folder = str(tpl)
    config.tpl_manifest = ""
    # 其余叠层（横条/顶部台阶/贴纸）会盖在取样点上，量像素前先关掉；
    # 它们与模板无关，各自另有测试
    for key in ("top_step_enabled", "bars_enabled", "moving_sticker_enabled",
                "sticker_enabled", "kaimu_enabled", "scanlight_enabled"):
        setattr(config, key, False)
    defaults = {"tpl_window_center_x": 50, "tpl_window_center_y": 50,
                "tpl_window_w": 80, "tpl_window_h": 55, "tpl_window_feather": 60}
    for name, value in defaults.items():
        setattr(config, name, window.get(name, value))

    if not process_batch(config, folder):
        return None
    output = next((folder / "out").glob("*.mp4"))
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.5",
         "-i", str(output), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    output.unlink()

    def pixel(x: int, y: int):
        index = (y * CANVAS_W + x) * 3
        return raw[index], raw[index + 1], raw[index + 2]

    return pixel


def _is_template(rgb) -> bool:
    # 模板是纯绿 (0,126,0)
    return rgb[1] > 100 and rgb[0] < 80 and rgb[2] < 80


def check_end_to_end(folder: Path) -> int:
    """端到端：窗口内是主视频，四周是模板。"""
    failures = 0
    pixel = _render(folder, _green_template(folder))
    if pixel is None:
        print("  端到端：失败（背景目录为空时应仍可运行）")
        return 1

    for name, (x, y) in CORNERS:
        if not _is_template(pixel(x, y)):
            failures += 1
            print(f"  失败 {name}角不是模板: {pixel(x, y)}")
    # 窗口中心必须是主视频（testsrc2 是彩色图案，不会是纯绿）
    if _is_template(pixel(*CENTER)):
        failures += 1
        print(f"  失败 窗口中心仍是模板: {pixel(*CENTER)}")
    # 窗口左右外侧应是模板
    for x in (5, CANVAS_W - 6):
        if not _is_template(pixel(x, CANVAS_H // 2)):
            failures += 1
            print(f"  失败 x={x} 应是模板: {pixel(x, CANVAS_H // 2)}")

    print(f"  端到端（窗口内主视频+四周模板）：{'通过' if not failures else '失败'}")
    return failures


def check_window_polarity(folder: Path) -> int:
    """窗口内外不能反：alpha=255 是主视频可见，所以窗口内给 255。

    这里换成**纯色**的主视频（红）与模板（绿），判据才不含糊：落在窗口内
    必须是红、落在窗口外必须是绿。极性反了这个用例会成片失败。
    """
    failures = 0
    tpl = _green_template(folder)
    main = folder / "纯红"
    main.mkdir(exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "color=red:s=320x240:r=15:d=2",
            "-pix_fmt", "yuv420p", str(main / "红.mp4"))

    def is_main(rgb) -> bool:
        return rgb[0] > 120 and rgb[1] < 90 and rgb[2] < 90

    # 小窗口居中（20%x20% → x144~216 / y256~384）：中心在窗口内，LEFT 在窗口外
    pixel = _render(folder, tpl, main, tpl_window_w=20, tpl_window_h=20,
                    tpl_window_feather=0)
    if pixel is None:
        print("  窗口极性：失败（小窗口批处理未成功）")
        return 1
    if not is_main(pixel(*CENTER)):
        failures += 1
        print(f"  失败 窗口内应是主视频，实得 {pixel(*CENTER)}")
    if not _is_template(pixel(*LEFT)):
        failures += 1
        print(f"  失败 窗口外应是模板，实得 {pixel(*LEFT)}")

    # 窗口比画布大 = 不挖洞：主视频帧内处处都该是主视频
    pixel = _render(folder, tpl, main, tpl_window_w=120, tpl_window_h=120,
                    tpl_window_feather=0)
    if pixel is None:
        failures += 1
        print("  窗口极性：失败（全窗口批处理未成功）")
    elif not is_main(pixel(*LEFT)):
        failures += 1
        print(f"  失败 全窗口时窗口外也该是主视频，实得 {pixel(*LEFT)}")

    # 窗口整个推出画布 = 全被模板挡住
    pixel = _render(folder, tpl, main, tpl_window_w=20, tpl_window_h=20,
                    tpl_window_center_x=200, tpl_window_feather=0)
    if pixel is None:
        failures += 1
        print("  窗口极性：失败（推离画布批处理未成功）")
    else:
        for name, (x, y) in (("中心", CENTER), ("左侧", LEFT)):
            if not _is_template(pixel(x, y)):
                failures += 1
                print(f"  失败 窗口推出画布后{name}应是模板，实得 {pixel(x, y)}")

    print(f"  窗口极性（内=主视频 / 外=模板）：{'通过' if not failures else '失败'}")
    return failures


def check_template_survives_delete_used_aux(folder: Path) -> int:
    """模板是可复用库：用完即删开关不能把模板本身删掉。"""
    failures = 0
    tpl = folder / "模板2"
    tpl.mkdir(exist_ok=True)
    template = tpl / "要保住的模板.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=green:s=720x1280:r=15:d=1",
            "-pix_fmt", "yuv420p", str(template))

    config = _config(folder)
    config.background_folder = str(folder / "空背景")
    config.tpl_enabled = True
    config.tpl_folder = str(tpl)
    config.tpl_manifest = ""
    config.delete_used_aux = True          # 关键：模板模式下必须被忽略

    if not process_batch(config, folder):
        failures += 1
        print("  失败 模板批处理未成功")
        print("  模板不被删除：失败")
        return failures

    if not template.exists():
        failures += 1
        print(f"  失败 模板被 delete_used_aux 删掉了: {template}")

    for leftover in (folder / "out").glob("*.mp4"):
        leftover.unlink()
    print(f"  模板不被删除（忽略 delete_used_aux）：{'通过' if not failures else '失败'}")
    return failures


def check_window_opacity(folder: Path) -> int:
    """窗口内必须**完全不透明**，且羽化带落在窗口边上。

    主视频纯黑、模板纯白时，窗口内像素 = 255*(1-alpha)：alpha 满量程是 0。
    蒙版少了那次二值化的话 alpha 只有 235/255，会留下约 20 的灰 —— 实拍就是
    「主视频发灰、模板透了一层」，肉眼几乎看不出来，只能这样钉。
    """
    failures = 0
    tpl = folder / "白模板"
    tpl.mkdir(exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "color=white:s=720x1280:r=15:d=2",
            "-pix_fmt", "yuv420p", str(tpl / "白.mp4"))
    main = folder / "纯黑"
    main.mkdir(exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "color=black:s=320x240:r=15:d=2",
            "-pix_fmt", "yuv420p", str(main / "黑.mp4"))

    pixel = _render(folder, tpl, main, tpl_window_feather=60)
    if pixel is None:
        print("  窗口不透明：失败（批处理未成功）")
        return 1
    centre = pixel(*CENTER)[0]
    if centre > 6:
        failures += 1
        print(f"  失败 窗口内应是主视频（黑），实得 {centre} —— 蒙版不是满量程")
    outside = pixel(5, CANVAS_H // 2)[0]
    if outside < 245:
        failures += 1
        print(f"  失败 窗口外应是模板（白），实得 {outside}")

    # 羽化带要压在窗口边上：取 50%x50% 窗口（画布上 x=90~270），
    # 窗口左边界那一点该是一半一半
    pixel = _render(folder, tpl, main, tpl_window_w=50, tpl_window_h=50,
                    tpl_window_feather=60)
    if pixel is None:
        failures += 1
        print("  窗口不透明：失败（半窗口批处理未成功）")
    else:
        edge = pixel(90, CANVAS_H // 2)[0]
        if not 100 <= edge <= 155:
            failures += 1
            print(f"  失败 窗口边界应是半透明过渡，实得 {edge}")
        # 同一行再往里 20px 就该完全透出主视频
        inside = pixel(120, CANVAS_H // 2)[0]
        if inside > 6:
            failures += 1
            print(f"  失败 窗口内 20px 处应已完全不透明，实得 {inside}")

    print(f"  窗口不透明与羽化位置：{'通过' if not failures else '失败'}")
    return failures


def demo() -> None:
    print("== 模板通道 ==")
    with TemporaryDirectory() as tmp:
        folder = Path(tmp)
        _assets(folder)
        failures = 0
        failures += check_backward_compatible(folder)
        failures += check_window_math(folder)
        failures += check_manifest_precedence(folder)
        failures += _picks(folder)
        failures += check_end_to_end(folder)
        failures += check_window_polarity(folder)
        failures += check_window_opacity(folder)
        failures += check_template_survives_delete_used_aux(folder)
    assert failures == 0, f"{failures} 项失败"
    print("template overlay test: OK")


if __name__ == "__main__":
    demo()
