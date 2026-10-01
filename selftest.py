"""当前本地版的快速自检入口。"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.pipeline import self_test as pipeline_self_test  # noqa: E402
from modes import load_modes  # noqa: E402


def main() -> int:
    groups = load_modes()
    if len(groups) != 8:
        print(f"[失败] 处理平台不完整：{list(groups)}")
        return 1
    if load_modes.errors:
        print("[失败] 模式加载错误：")
        print("\n".join(load_modes.errors))
        return 1
    print(f"[OK] 已加载 8 个平台、{sum(map(len, groups.values()))} 个通道")
    return 0 if pipeline_self_test(ROOT) else 1


if __name__ == "__main__":
    raise SystemExit(main())
