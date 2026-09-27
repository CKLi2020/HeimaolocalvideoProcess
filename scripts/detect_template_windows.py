"""离线探测模板的中央窗口，生成 `模板.json` 清单，并输出拼接对照图供肉眼复核。

不进发布包。用法：

    "%LocalAppData%\\Programs\\Python\\Python39\\python.exe" ^
        scripts\\detect_template_windows.py "模板" --canvas 1080x2338 ^
        --sheet docs\\calibration\\template_windows.png

为什么需要换算
--------------
模板（例如 1080x1920）与画布（例如 1080x2338）纵横比常常不同。背景/模板走的是
`scale=...:force_original_aspect_ratio=increase,crop=...`，即**等比放大到铺满画布、
再居中裁掉溢出**。所以模板内的百分比与画布百分比不是一回事：本例中模板被放大
2338/1920 倍后左右各裁掉 117px。探测是在模板自身帧上做的，写进清单前必须按同一
套 increase+crop 规则换算到画布坐标系，否则窗口会整体错位。

这个换算与 engine/ffmpeg_builder.py 的背景滤镜是同一条规则；`tests/test_template_overlay.py`
里有用例把换算结果与 ffmpeg 实际输出比对，防止两边漂移。

为什么用「平坦 + 同色」双条件
-----------------------------
单一条件都有反例，实测于「蝴蝶号离线版」的 40 个动态背景：

- 只按颜色：`上下留空动态背景` 的窗口是深色、四周也深色 → 连通域走穿到满屏。
- 只按平坦：`photo_flower_*` 的窗口近白、窗外也是大片近白 → 同样走穿。

两者取交集后，颜色能挡住「外面平坦但不同色」，平坦能挡住「外面同色但有纹理」。
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.ffmpeg_builder import VIDEO_EXTS, list_media  # noqa: E402

WINDOW_FIELDS = ("window_center_x", "window_center_y", "window_w", "window_h")

PROBE_W, PROBE_H = 270, 480      # 探测分辨率：够精确，又让纯 Python 遍历足够快
TIGHT_TOL = 6                    # 定横向跨度用的紧容差
COLOR_TOL = 22                   # 行/列均值与中心色的最大差
SPREAD_TOL = 8                   # 行内/列内极差上限（窗口内部实测 0~6，装饰 100~255）
MARGIN_FRAC = 0.06               # 算行内极差时两端各让出的比例，避开圆角/边框
SAMPLES = (0.15, 0.5, 0.8)       # 采样帧位置（占总时长的比例）
SHEET_W, SHEET_H = 200, 356      # 对照图里每个缩略图的尺寸
MIN_W_PCT, MAX_W_PCT = 30.0, 100.0
MIN_H_PCT, MAX_H_PCT = 20.0, 100.0

# 为什么不是「与中心像素比颜色」的单条件
# ------------------------------------
# 单条件在实测的 40 个模板上都有反例：
# - 只比颜色：`上下留空动态背景` 的窗口是深色、四周也深色，连通域直接走穿满屏。
#   更糟的是窗口内部还带纵向渐变，紧容差让纵向提前停住（樱花晨光只走出 10.8%），
#   放宽又冲进背景。
# - 只比平坦：`无向日葵` 窗口上方有一条纯粉色带（行内极差 0），会把窗口往上撑到 70%。
#
# 所以用「行内极差小 **且** 该行颜色接近中心色」两个条件：极差挡住有纹理的装饰行，
# 颜色挡住窗外那些同样均匀但不同色的平坦带。
#
# 边界本身是模糊的：photo_* 的窗口边界是渐变过渡，樱花晨光的窗口顶部被花带压住。
# 因此这里追求的是「落在几趴以内」，不是像素级精确 —— 差几趴视觉上无害。


def probe(path: Path) -> tuple[int, int, float]:
    """返回 (宽, 高, 时长秒)。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    stream = json.loads(out)["streams"][0]

    # 部分容器不写 stream.duration，回退到 format.duration
    duration = stream.get("duration")
    if duration in (None, "N/A"):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
        duration = json.loads(out)["format"].get("duration", "0")
    return int(stream["width"]), int(stream["height"]), float(duration or 0.0)


def frame_rgb(path: Path, ts: float) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{ts:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", f"scale={PROBE_W}:{PROBE_H}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout


def _px(buf: bytes, x: int, y: int) -> tuple[int, int, int]:
    i = (y * PROBE_W + x) * 3
    return buf[i], buf[i + 1], buf[i + 2]


def _stats(buf: bytes, axis: str, index: int, lo: int, hi: int):
    """沿 axis('x' 或 'y') 的直线，统计 [lo,hi] 上的极差与均值。"""
    low = high = None
    total = [0, 0, 0]
    count = 0
    for step in range(lo, hi + 1):
        p = _px(buf, step, index) if axis == "x" else _px(buf, index, step)
        if low is None:
            low, high = list(p), list(p)
        for k in range(3):
            if p[k] < low[k]:
                low[k] = p[k]
            if p[k] > high[k]:
                high[k] = p[k]
            total[k] += p[k]
        count += 1
    if not count:
        return 10 ** 6, (0.0, 0.0, 0.0)
    spread = max(high[k] - low[k] for k in range(3))
    return spread, tuple(total[k] / count for k in range(3))


def _matches(spread: float, mean, seed) -> bool:
    """窗口判据：这一行/列既要均匀，颜色又要接近中心色。"""
    if spread > SPREAD_TOL:
        return False
    return max(abs(mean[k] - seed[k]) for k in range(3)) <= COLOR_TOL


def _max_run(flags: list[bool], start: int):
    """包含 start 的最大连续 True 段。"""
    if not flags[start]:
        return None
    lo = start
    while lo > 0 and flags[lo - 1]:
        lo -= 1
    hi = start
    while hi < len(flags) - 1 and flags[hi + 1]:
        hi += 1
    return lo, hi


def detect_once(buf: bytes) -> tuple[int, int, int, int] | None:
    """返回窗口 bbox（探测坐标）；判不出来返回 None。

    步骤：紧容差定横向跨度 → 找均匀行段 → 用行段反过来细化横向跨度。
    两个方向互相约束，避免单向判据跑偏。
    """
    if len(buf) < PROBE_W * PROBE_H * 3:
        return None
    cx, cy = PROBE_W // 2, PROBE_H // 2
    seed = _px(buf, cx, cy)

    # 1) 初始横向跨度：从中心向两侧紧容差走
    xl = cx
    while xl > 0 and max(abs(_px(buf, xl - 1, cy)[k] - seed[k])
                         for k in range(3)) <= TIGHT_TOL:
        xl -= 1
    xr = cx
    while xr < PROBE_W - 1 and max(abs(_px(buf, xr + 1, cy)[k] - seed[k])
                                   for k in range(3)) <= TIGHT_TOL:
        xr += 1

    def run_along(span_lo: int, span_hi: int, axis: str, start: int):
        """在 [span_lo, span_hi] 上逐条线判均匀，取包含 start 的最大段。"""
        margin = max(2, int((span_hi - span_lo + 1) * MARGIN_FRAC))
        lo, hi = span_lo + margin, span_hi - margin
        if hi <= lo:
            return None
        size = PROBE_H if axis == "x" else PROBE_W
        flags = [_matches(*_stats(buf, axis, i, lo, hi), seed)
                 for i in range(size)]
        return _max_run(flags, start)

    # 2) 找均匀行段（固定 y、沿线取 x）
    vertical = run_along(xl, xr, "x", cy)
    if vertical is None:
        return None
    yt, yb = vertical

    # 3) 用行段反过来细化横向跨度（固定 x、沿线取 y）
    horizontal = run_along(yt, yb, "y", cx)
    if horizontal is None:
        return None
    xl2, xr2 = horizontal

    w = xr2 - xl2 + 1
    h = yb - yt + 1
    if w < PROBE_W * 0.2 or h < PROBE_H * 0.1:
        return None
    # 贴到探测帧边缘：说明判据没找到边界，宁可判失败也不要给个错值
    if xl2 == 0 or xr2 == PROBE_W - 1 or yt == 0 or yb == PROBE_H - 1:
        return None
    return xl2, yt, w, h


def detect_window(path: Path) -> tuple[int, int, int, int] | None:
    """抽多帧探测取中位数 bbox（探测坐标），全部失败返回 None。"""
    _, _, duration = probe(path)
    boxes = []
    for fraction in SAMPLES:
        ts = max(0.0, duration * fraction)
        try:
            box = detect_once(frame_rgb(path, ts))
        except subprocess.CalledProcessError:
            continue
        if box:
            boxes.append(box)
    if not boxes:
        return None
    return tuple(int(statistics.median([b[i] for b in boxes])) for i in range(4))


def rescale_box(box, size: tuple[int, int]) -> tuple[int, int, int, int]:
    """探测坐标 → 目标尺寸下的像素框。

    探测帧是缩放过的（例如原生 1080x1920 → 探测 270x480），探测坐标不能直接
    和原生像素、缩略图像素混用，否则结果整体偏小或画到画面外。两处消费方
    （写清单时还原到原生像素、画对照图时落到缩略图空间）都经这里换算。
    """
    fx = size[0] / PROBE_W
    fy = size[1] / PROBE_H
    factors = (fx, fy, fx, fy)          # (x, y, w, h) 各自的缩放
    return tuple(int(round(value * factors[i])) for i, value in enumerate(box))


def to_template_pct(box) -> dict:
    """探测框 → 模板空间百分比。用于合理性校验。

    校验必须在模板空间做：模板与画布纵横比不同，换成画布百分比后窗口宽
    完全可能超过 100%（模板比画布宽时），那不代表探测失败。
    """
    x, y, w, h = box
    return {
        "window_center_x": (x + w / 2) / PROBE_W * 100,
        "window_center_y": (y + h / 2) / PROBE_H * 100,
        "window_w": w / PROBE_W * 100,
        "window_h": h / PROBE_H * 100,
    }


def to_canvas_pct(probe_box, native: tuple[int, int], canvas: tuple[int, int]) -> dict:
    """探测坐标的窗口框 → 画布百分比，按背景的 increase+crop 规则换算。

    模板与画布纵横比常常不同，背景是「等比放大到铺满、再居中裁掉溢出」，
    所以模板内的百分比不等于画布百分比，必须走这一步换算。
    """
    bx, by, bw, bh = rescale_box(probe_box, native)
    tw, th = native
    cw, ch = canvas
    scale = max(cw / tw, ch / th)              # increase：铺满
    off_x = (tw * scale - cw) / 2              # crop：居中裁掉溢出
    off_y = (th * scale - ch) / 2

    x = bx * scale - off_x
    y = by * scale - off_y
    w = bw * scale
    h = bh * scale

    def pct(value: float, span: int) -> int:
        return int(round(value / span * 100))

    return {
        "window_center_x": pct(x + w / 2, cw),
        "window_center_y": pct(y + h / 2, ch),
        "window_w": pct(w, cw),
        "window_h": pct(h, ch),
    }


def render_sheet(entries: list[dict], out_path: Path) -> bool:
    """把探测框画在缩略图上拼成一张对照图，供肉眼复核。"""
    if not entries:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for index, entry in enumerate(entries, start=1):
            box = entry.get("box")
            if box:
                # drawbox 在 scale 之后生效，坐标必须落在缩略图空间
                dx, dy, dw, dh = rescale_box(box, (SHEET_W, SHEET_H))
                color = "lime" if entry["ok"] else "red"
                draw = f",drawbox=x={dx}:y={dy}:w={dw}:h={dh}:color={color}:t=3"
            else:
                draw = ""
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(entry["path"]),
                 "-frames:v", "1", "-vf", f"scale={SHEET_W}:{SHEET_H}{draw}",
                 str(tmpdir / f"{index}.png")],
                check=True,
            )
        columns = min(8, len(entries))
        rows = (len(entries) + columns - 1) // columns
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(tmpdir / "%d.png"),
             "-vf", f"tile={columns}x{rows}", "-frames:v", "1", str(out_path)],
            check=True,
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="探测模板中央窗口并生成清单")
    parser.add_argument("folder", nargs="?", default="模板", help="模板库目录")
    parser.add_argument("--manifest", default="模板.json", help="清单文件名")
    parser.add_argument("--canvas", default=None,
                        help="画布 WxH，默认读 config.json 的 resolution")
    parser.add_argument("--sheet", default=None,
                        help="对照图输出路径，默认 <folder>/窗口探测对照图.png")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写清单")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        print(f"[错误] 模板目录不存在: {folder}")
        return 1

    if args.canvas:
        canvas = tuple(int(v) for v in args.canvas.lower().split("x"))
    else:
        raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        canvas = tuple(int(v) for v in raw["resolution"].lower().split("x"))
    if len(canvas) != 2:
        print("[错误] 画布格式应为 WxH")
        return 1
    print(f"画布 {canvas[0]}x{canvas[1]}  （画布改了必须重跑本脚本）")

    files = list_media(str(folder), VIDEO_EXTS)
    if not files:
        print(f"[错误] 目录中没有视频: {folder}")
        return 1

    entries, overrides, stats = [], [], {"ok": 0, "leak": 0}
    for path in files:
        native = probe(path)[:2]
        box = detect_window(path)
        values = None
        if box is None:
            ok = False
        else:
            local = to_template_pct(box)
            ok = (MIN_W_PCT <= local["window_w"] <= MAX_W_PCT
                  and MIN_H_PCT <= local["window_h"] <= MAX_H_PCT)
            if ok:
                values = to_canvas_pct(box, native, canvas)
        stats["ok" if ok else "leak"] += 1
        entries.append({
            "path": path, "native": native, "box": box, "ok": ok, "values": values,
        })
        marker = "OK " if ok else "!! "
        if box is None:
            detail = "探测失败（找不到窗口边界）"
        else:
            local = to_template_pct(box)
            detail = (f"模板内 {local['window_w']:.0f}%x{local['window_h']:.0f}% "
                      f"@({local['window_center_x']:.0f},{local['window_center_y']:.0f})")
            if values is not None:
                detail += (f"  → 画布 {values['window_w']}%x{values['window_h']}% "
                           f"@({values['window_center_x']},{values['window_center_y']})")
        print(f"  {marker}{path.name}  原生{native[0]}x{native[1]}  {detail}")
        if ok:
            overrides.append({"file": path.name, **values})

    middle = {
        field: int(round(statistics.median([o[field] for o in overrides])))
        for field in WINDOW_FIELDS
    } if overrides else None

    print(f"\n{len(entries)} 个模板：可靠 {stats['ok']}，失败 {stats['leak']}")
    if middle:
        print(f"可靠模板的窗口中位数: "
              f"{middle['window_w']}%x{middle['window_h']}% "
              f"@({middle['window_center_x']},{middle['window_center_y']})")

    sheet = Path(args.sheet) if args.sheet else folder / "窗口探测对照图.png"
    try:
        if render_sheet(entries, sheet):
            print(f"对照图（绿框=可靠，红框=失败）: {sheet}")
    except subprocess.CalledProcessError as exc:
        print(f"[警告] 对照图生成失败: {exc}")

    if args.dry_run:
        print("--dry-run：未写清单")
        return 0

    manifest = {
        "version": 1,
        "_生成方式": f"scripts/detect_template_windows.py --canvas {canvas[0]}x{canvas[1]}",
        "_画布": f"{canvas[0]}x{canvas[1]}",
        "_说明": "本文件的窗口值是画布百分比。改动画布后必须重新生成。",
    }
    if middle:
        manifest["defaults"] = middle
    manifest["templates"] = overrides

    target = folder / args.manifest
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"已写入清单: {target}")
    print(f"  defaults（{len(overrides)} 个可靠模板的中位数）+ "
          f"{len(overrides)} 条逐模板覆盖")
    print(f"  探测失败的那些没有逐模板条目，会套用 defaults（即上面那个中位数）；"
          f"需要时可手工在清单里补一条 override。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
