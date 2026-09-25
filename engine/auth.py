"""授权缝与受保护核心的稳定 Python 调用接口。

背景
----
原实现里核心算法锁在 app/_flowcut_core.pyd：
  - mask_alpha            无授权版本，可直接调用
  - authorized_mask_alpha 需服务器令牌，内部验签，假令牌抛「令牌格式无效」
  - authorized_butterfly_plan  无授权版本，需服务器令牌
  - task_claims           编译期门禁

当前版本去掉服务器门禁，但正式发布仍从受 VMProtect 保护的
``app._flowcut_core`` 执行核心计算。源码调试时由 ``engine.dev_core`` 提供
等价实现；Nuitka 发布构建明确排除该调试模块。

换新授权服务器时怎么接
----------------------
只需改本文件：
  - get_task_scope() 改为返回真 scope（fetch 令牌后构造 dict）
  - 需要门禁的算法改为先校验 scope 再调用本地实现
引擎侧不需要任何改动 —— 它们只认 task_scope 的真假。

等价性验证
----------
- mask_alpha：与编译版逐组比对，见 tests/test_local_mask_alpha.py
  （编译版无需令牌，可随时重跑）
- butterfly_plan：与真机抓取的输出比对，见
  tests/test_butterfly_plan_parity.py 与 docs/calibration/
"""

from __future__ import annotations

from typing import Callable, Optional

from engine.native_core import core as _native_core

def mask_alpha(
    w: int,
    h: int,
    feather: int,
    margin_tb: float,
    margin_lr: float,
) -> str:
    """返回 ffmpeg geq 滤镜的 alpha 表达式字符串。

    与 app._flowcut_core.mask_alpha 等价（已在参数网格上逐组比对）。

    语义：保留画面中部 (1 - 2*margin) 的区域，边缘按 feather 羽化。
    margin_tb / margin_lr 是 0~0.5 的比例，feather 以 1080 短边为基准缩放。

    两个 margin 都为 0 时返回空字符串 —— 调用方据此走 null 分支。
    """
    return _native_core.mask_alpha(w, h, feather, margin_tb, margin_lr)


def butterfly_plan(
    duration: float,
    head: float,
    hidden: Optional[float] = None,
    fps: int = 30,
) -> dict:
    """返回蝴蝶AB 编辑列表计划，键同 authorized_butterfly_plan。

    纯确定性函数，无随机性。语义：A头(head) + 隐藏段(hidden) + A尾，
    通过编辑列表让平台跳过中间段。

    Args:
        duration: 主视频时长（秒）
        head: A 头长度（秒）
        hidden: 隐藏段时长；None 时按 duration + 2 帧 计算
        fps: 帧率，用于换算帧号

    Returns:
        {"hidden": float, "chunks": [float, ...],
         "jump_frame": int, "main_frames": int}
    """
    return _native_core.butterfly_plan(duration, head, hidden, fps)


def get_task_scope() -> Optional[dict]:
    """返回当前任务的授权 scope。

    本地模式返回 None —— 引擎把 None 视为「无需门禁，走本地算法」。
    接入新服务器时改为：取令牌 → 构造 scope dict → 返回；引擎侧零改动。
    """
    return None


# 兼容旧调用形态：原代码用 task_scope_provider 是 Callable[[], dict]
def as_provider() -> Callable[[], Optional[dict]]:
    return get_task_scope


# ─────────────────────────────────────────────────────────────────────
# 门禁：整个引擎只有一个调用点（engine.pipeline.process_batch 入口）。
# 接入新授权服务器时，在程序入口调用 set_gate(你的门禁) 一次即可，
# 引擎代码零改动 —— 这就是当初「换服务器不用动引擎」想要的效果。
# ─────────────────────────────────────────────────────────────────────

# 门禁签名：(引擎名, 任务信息) -> None/True 放行；False 拒绝；抛异常亦可
Gate = Callable[[str, dict], Optional[bool]]


def local_gate(engine: str, job: dict) -> Optional[bool]:
    """本地模式门禁：不校验，一律放行。"""
    return None


_gate: Gate = local_gate


def set_gate(gate: Gate) -> None:
    """替换门禁实现。接入新服务器时在入口处调用一次。"""
    global _gate
    _gate = gate


def check(engine: str, job: dict) -> None:
    """引擎侧唯一的门禁入口。

    Raises:
        PermissionError: 门禁明确拒绝时。
    """
    if _gate(engine, job) is False:
        raise PermissionError(f"未授权：{engine}")
