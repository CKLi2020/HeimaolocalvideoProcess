"""验证 engine.auth.butterfly_plan 与编译版 authorized_butterfly_plan 等价。

基准数据来自 docs/calibration/butterfly_plan.json（由 docs/archive/calibrate_flowcut_core.py
在去授权之前、用真卡密换真令牌抓取；该脚本与旧授权服务器一并下线后已归档）。编译版没有免授权的 butterfly_plan，
所以只能对基准回归，无法像 mask_alpha 那样实时比对。

判定比 mask_alpha 严：不仅 hidden/jump_frame/main_frames 要一致，chunks 列表
必须**逐元素、逐浮点**相同 —— 该函数下游直接拼 ffmpeg 的 trim/setpts，
浮点噪声也会让 PTS 位移（见 engine/butterfly_ab.py 的 hide_middle）。

用法：python tests\\test_butterfly_plan_parity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.auth import butterfly_plan  # noqa: E402

DUMP = ROOT / "docs" / "calibration" / "butterfly_plan.json"
FPS = 30

# 手工边界用例：这些是「余量 0.02 阈值」与「空 chunks」两条分支的判别样本，
# 贪心实现（永远追加余量）会在此全部失败。已在真机上核实（见模块文档）。
# 期望值里保留浮点噪声，因为源码就是把 hidden - sum(chunks) 原样追加。
EDGE_CASES = [
    # (duration, head, hidden, 期望 chunks)
    (30.0, 0.3, 23.01, [23.0]),                      # 余量 0.01 → 丢弃
    (30.0, 0.3, 23.02, [23.0]),                      # 余量 0.02 → 丢弃（> 为假）
    (30.0, 0.3, 23.03, [23.0, 0.030000000000001137]),  # 余量 0.03 → 追加
    (30.0, 0.3, 46.01, [23.0, 23.0]),                # 两块 + 余量 0.01 丢弃
    (30.0, 0.3, 22.99, [22.99]),                     # 不足一块 → 单块
    (30.0, 0.3, 0.01, []),                           # 不足阈值且不足一块 → 空
]


def _parse_key(key: str):
    duration, head, hidden = key.split("|")
    value = None if hidden[2:] == "None" else float(hidden[2:])
    return float(duration[1:]), float(head[1:]), value


def _diff(expected: dict, actual: dict) -> str | None:
    """返回差异说明；一致则返回 None。"""
    for field in ("hidden", "jump_frame", "main_frames"):
        if expected[field] != actual[field]:
            return f"{field}: 基准 {expected[field]!r} != 本地 {actual[field]!r}"
    # chunks 逐元素比较，且长度必须相同
    if len(expected["chunks"]) != len(actual["chunks"]):
        return f"chunks 长度: 基准 {expected['chunks']!r} != 本地 {actual['chunks']!r}"
    for index, (want, got) in enumerate(zip(expected["chunks"], actual["chunks"])):
        if want != got:
            return f"chunks[{index}]: 基准 {want!r} != 本地 {got!r}"
    return None


def check_edge_cases() -> int:
    failures = 0
    for duration, head, hidden, want_chunks in EDGE_CASES:
        actual = butterfly_plan(duration, head, hidden, FPS)
        if actual["chunks"] != want_chunks or actual["hidden"] != float(hidden):
            failures += 1
            print(f"  MISMATCH d={duration} h={head} hd={hidden}")
            print(f"    期望 chunks {want_chunks!r} / hidden {float(hidden)!r}")
            print(f"    本地 chunks {actual['chunks']!r} / hidden {actual['hidden']!r}")
    print(f"  边界用例：{len(EDGE_CASES) - failures}/{len(EDGE_CASES)} 通过")
    return failures


def check_against_dump() -> int:
    if not DUMP.exists():
        print(f"  基准文件不存在：{DUMP}")
        print("  跳过（基准由 docs/archive/calibrate_flowcut_core.py 生成，已归档）")
        return 0

    data = json.loads(DUMP.read_text(encoding="utf-8"))
    failed = 0
    total = 0
    for key, expected in data.items():
        if not isinstance(expected, dict) or "__error__" in expected:
            continue  # 抓取时出错的条目
        total += 1
        duration, head, hidden = _parse_key(key)
        actual = butterfly_plan(duration, head, hidden, FPS)
        reason = _diff(expected, actual)
        if reason:
            failed += 1
            if failed <= 5:
                print(f"  MISMATCH {key}")
                print(f"    {reason}")
    print(f"  基准比对：{total - failed}/{total} 通过")
    return failed


def demo() -> None:
    print("== 本地 butterfly_plan 等价性 ==")
    failed = check_edge_cases() + check_against_dump()
    assert failed == 0, f"{failed} 组不一致"
    print("local butterfly_plan parity test: OK")


if __name__ == "__main__":
    demo()
