"""一次性校准脚本：抓取编译模块 app._flowcut_core 的真实输出，供本地重写对齐。

必须在本机卡密仍有效、旧授权服务器仍可达时运行 —— 这是去授权之前唯一
不可事后补做的步骤。

用法（仓库根目录下）：
    "%LocalAppData%\\Programs\\Python\\Python39\\python.exe" scripts\\calibrate_flowcut_core.py

特性：
  - 可续跑：已抓到的组合会跳过，反复运行直到补全。
  - 主动限流：服务器会返回「任务授权请求过于频繁」，脚本按 backoff 重试。

产出：
    docs/calibration/mask_alpha.json        （无需令牌，任何时候都能重跑）
    docs/calibration/butterfly_plan.json    （需要真令牌）

本脚本不进发布包。
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT_DIR = ROOT / "docs" / "calibration"
PLAN_JSON = OUT_DIR / "butterfly_plan.json"
MASK_JSON = OUT_DIR / "mask_alpha.json"

# ── 限流参数（服务器会拒绝高频请求）──
REQUEST_INTERVAL = 4.0      # 每次成功请求之间的间隔（秒）
RATE_LIMIT_BACKOFF = 25.0   # 被限流后的等待（秒）
MAX_ATTEMPTS = 6

# ── 蒙版参数网格 ───────────────────────────────────────────────────────
CANVASES = [
    (1080, 1920), (1080, 2338), (1920, 1080), (2338, 1080),
    (1280, 720), (720, 1280), (540, 960), (360, 640),
    (480, 854), (2160, 3840), (1080, 1080), (64, 64),
]
FEATHERS = [0, 1, 2, 3, 5, 7, 10, 13, 17, 20, 26, 33, 45, 60]
MARGINS = [0, 0.005, 0.01, 0.05, 0.1, 0.2, 0.35, 0.5]

# ── 蝴蝶计划参数网格 ───────────────────────────────────────────────────
# native_src/flowcut_core.pyx 的 _butterfly_plan 已给出实现，但其中一条分支
# 在采样网格上不可区分，故仍用真机钉死：
#   chunks = [23.0] * int(hidden // 23)
#   if hidden - sum(chunks) > 0.02: chunks.append(余量)   ← 余量落在 (0,0.02] 时被丢弃
# 阶段 4 专门构造余量贴近 0.02 的 hidden 来区分「丢弃」与「永远追加」。
BUTTERFLY_GRID: list[tuple[float, float, float | None]] = []

# 1) 全时长扫描：head 固定 0.3，hidden 交给内部公式
for _d in [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 23.0, 30.0, 60.0, 120.0, 300.0]:
    BUTTERFLY_GRID.append((_d, 0.3, None))

# 2) 23 秒边界附近（B 素材长度），用于确认切片阈值
for _d in [22.0, 24.0, 46.0, 69.0]:
    BUTTERFLY_GRID.append((_d, 0.3, None))

# 3) 显式 hidden：验证「给定值原样透传」以及跨 23s 的切分
for _d, _hd in [(30.0, 23.0), (30.0, 24.0), (60.0, 10.0), (60.0, 25.0), (60.0, 50.0)]:
    BUTTERFLY_GRID.append((_d, 0.3, _hd))

# 4) 余量阈值判别样本（决定性）：hidden 卡在 23 的整数倍附近。
#    余量 <=0.02 → 源码丢弃该余量，chunks 总长会短于 hidden；
#    余量  >0.02 → 追加。另含 hidden<23 与 hidden<0.02 的边界。
for _d, _hd in [
    (30.0, 23.01),    # 余量 0.01  → 期望 chunks=[23.0]（丢弃）
    (30.0, 23.02),    # 余量 0.02  → 期望丢弃（>0.02 为假）
    (30.0, 23.03),    # 余量 0.03  → 期望追加
    (30.0, 46.01),    # 两块 + 余量 0.01 → 期望 [23.0,23.0]
    (30.0, 22.99),    # 不足一块 → 期望 [22.99]
    (30.0, 0.01),     # 小于阈值且不足一块 → 期望 []（空列表）
]:
    BUTTERFLY_GRID.append((_d, 0.3, _hd))

FPS = 30


def capture_mask(core, sink: dict) -> None:
    """mask_alpha 无需令牌，直接抓参数网格。"""
    ok = 0
    for w, h in CANVASES:
        for feather in FEATHERS:
            for tb in MARGINS:
                for lr in MARGINS:
                    key = f"{w}x{h}|f{feather}|tb{tb}|lr{lr}"
                    if key in sink:
                        continue
                    try:
                        sink[key] = core.mask_alpha(w, h, feather, tb, lr)
                        ok += 1
                    except Exception as exc:  # noqa: BLE001 - 记录而非中断
                        sink[key] = {"__error__": f"{type(exc).__name__}: {exc}"}
    print(f"[mask_alpha] new {ok}, total {len(sink)} combos")


def _is_rate_limit(exc: Exception) -> bool:
    return "频繁" in str(exc)


def capture_butterfly(core, license_client, sink: dict) -> None:
    """authorized_butterfly_plan 需要真令牌：逐组申请 + claim 后调用。"""
    params_hash = hashlib.sha256(b"calibration").hexdigest()
    engine = "flowcut-ab"
    done = 0
    skipped = 0
    failures: list[str] = []

    for duration, head, hidden in BUTTERFLY_GRID:
        if not 0 < head < duration:
            continue
        key = f"d{duration}|h{head}|hd{hidden}"
        if key in sink:
            skipped += 1
            continue

        batch_id = uuid.uuid4().hex
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                job_id = f"{batch_id}-1"
                token = license_client.task_token(
                    engine, batch_id, job_id, 1, params_hash
                )
                # worker.py 的顺序：先 task_token 再 task_claims，缺一不可
                core.task_claims(
                    token, engine, batch_id, job_id, 1, params_hash,
                    license_client.device_code, license_client.fingerprint,
                )
                sink[key] = core.authorized_butterfly_plan(
                    token, engine, batch_id, job_id, 1, params_hash,
                    license_client.device_code, license_client.fingerprint,
                    duration, head, hidden, FPS,
                )
                done += 1
                print(f"  OK  {key:26} -> {sink[key].get('chunks')}")
                # 每次成功后落盘，保证中断可续
                PLAN_JSON.write_text(
                    json.dumps(sink, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                time.sleep(REQUEST_INTERVAL)
                break
            except Exception as exc:  # noqa: BLE001
                if _is_rate_limit(exc) and attempt < MAX_ATTEMPTS:
                    print(f"  ..  限流，等待 {RATE_LIMIT_BACKOFF:.0f}s "
                          f"({attempt}/{MAX_ATTEMPTS}) {key}")
                    time.sleep(RATE_LIMIT_BACKOFF)
                    continue
                failures.append(f"{key}: {type(exc).__name__}: {exc}")
                print(f"  FAIL {key}: {type(exc).__name__}: {exc}")
                break

    print()
    print(f"[butterfly_plan] new {done}, skipped {skipped}, "
          f"failed {len(failures)}, total {len(sink)}")
    remaining = [
        f"d{d}|h{h}|hd{hd}" for d, h, hd in BUTTERFLY_GRID
        if 0 < h < d and f"d{d}|h{h}|hd{hd}" not in sink
    ]
    if remaining:
        print(f"  仍缺 {len(remaining)} 组，重跑本脚本可续抓：")


def main() -> int:
    import app._flowcut_core as core

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    mask_sink: dict = {}
    if MASK_JSON.exists():
        try:
            mask_sink = json.loads(MASK_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            mask_sink = {}
    capture_mask(core, mask_sink)
    MASK_JSON.write_text(
        json.dumps(mask_sink, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print()
    print("申请真令牌中（需要网络 + 有效卡密）...")
    try:
        from app.license import LicenseClient

        client = LicenseClient()
        if not client.has_license():
            print("  本机未保存卡密，跳过蝴蝶计划抓取。")
            return 0
        client.check()
        print(f"  授权通过：{client.api_base}")
    except Exception as exc:  # noqa: BLE001
        print(f"  授权失败：{type(exc).__name__}: {exc}")
        print("  退路：用 hidden = 主时长 + 2/fps 假设（已由首批数据证实），")
        print("        并用已产出的 蝴蝶AB成品/*.mp4 经 mp4_tool 读 elst 反推 chunks。")
        return 1

    plan_sink: dict = {}
    if PLAN_JSON.exists():
        try:
            plan_sink = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan_sink = {}
    capture_butterfly(core, client, plan_sink)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
