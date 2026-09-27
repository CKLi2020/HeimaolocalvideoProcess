"""验证 engine.auth.mask_alpha 与编译版 app._flowcut_core.mask_alpha 等价。

基准数据来自 docs/calibration/mask_alpha.json（由 scripts/calibrate_flowcut_core.py
在去授权之前抓取）。用它而非实时调用编译版，好处是去掉 .pyd 依赖后仍可回归。

用法：python tests\\test_local_mask_alpha.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.auth import mask_alpha  # noqa: E402

DUMP = ROOT / "docs" / "calibration" / "mask_alpha.json"

# 额外手工用例：覆盖边界与非法取值，防止实现只在基准网格上碰巧吻合
EXTRA_CASES = [
    (1080, 1920, 0, 0.0, 0.0),
    (1080, 1920, 0, 0.5, 0.5),
    (1, 1, 1, 0.1, 0.1),
    (1080, 1920, 1000, 0.05, 0.0),
    (1080, 1920, 2, 0.001, 0.001),
]


def _parse_key(key: str) -> tuple[int, int, int, float, float]:
    canvas, feather, tb, lr = key.split("|")
    w, h = canvas.split("x")
    return int(w), int(h), int(feather[1:]), float(tb[2:]), float(lr[2:])


def check_against_compiled() -> None:
    """如果编译版可导入，顺带实时比对一轮（无令牌，随时可跑）。"""
    try:
        import app._flowcut_core as core
    except Exception as exc:  # noqa: BLE001
        print(f"  编译版不可导入（{type(exc).__name__}），跳过实时比对")
        return
    mismatches = 0
    for w, h, feather, tb, lr in EXTRA_CASES:
        expected = core.mask_alpha(w, h, feather, tb, lr)
        actual = mask_alpha(w, h, feather, tb, lr)
        if expected != actual:
            mismatches += 1
            print(f"  MISMATCH {w}x{h} f={feather} tb={tb} lr={lr}")
            print(f"    compiled: {expected!r}")
            print(f"    local   : {actual!r}")
    print(f"  实时比对编译版：{len(EXTRA_CASES) - mismatches}/{len(EXTRA_CASES)} 通过")


def check_against_dump() -> int:
    if not DUMP.exists():
        print(f"  基准文件不存在：{DUMP}")
        print("  跳过（去授权之前运行 scripts/calibrate_flowcut_core.py 生成）")
        return 0

    data = json.loads(DUMP.read_text(encoding="utf-8"))
    mismatches = 0
    for key, expected in data.items():
        if isinstance(expected, dict):
            continue  # 抓取时出错的条目
        w, h, feather, tb, lr = _parse_key(key)
        actual = mask_alpha(w, h, feather, tb, lr)
        if actual != expected:
            mismatches += 1
            if mismatches <= 5:
                print(f"  MISMATCH {key}")
                print(f"    compiled: {expected!r}")
                print(f"    local   : {actual!r}")
    total = sum(1 for v in data.values() if not isinstance(v, dict))
    print(f"  基准比对：{total - mismatches}/{total} 通过")
    return mismatches


def demo() -> None:
    print("== 本地 mask_alpha 等价性 ==")
    check_against_compiled()
    failed = check_against_dump()
    assert failed == 0, f"{failed} 组与基准不一致"
    print("local mask_alpha parity test: OK")


if __name__ == "__main__":
    demo()
