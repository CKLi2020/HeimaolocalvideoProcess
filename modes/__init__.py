"""处理模式加载器(平台分组 · 下拉框版)。

- modes/ 下每个子目录 = 一个平台(如 douyin/ kuaishou/)
- 本地子目录里的 mode_*.py 只作为离线兜底/特殊参数扩展
- 模式定义(ffmpeg 命令模板等)放在 mode_defs/<平台>/<通道>.json
- 客户端启动时扫描这两处,自动刷新每个平台下拉框,新增通道不用改 Python

原版这一层是「客户端 modes/<平台>/mode_*.py ⇄ 宝塔 server_api/modes/<平台>/<通道>.json.php」,
客户端启动后向宝塔拉模式列表。宝塔已下线,本地版把服务端那半边换成了 mode_defs/ 目录 ——
扩展方式没变:丢一个 json 就多一个通道。

Nuitka 打包兼容: 打包后 .py 源文件不一定在 exe 旁,__file__ 也可能不指向真实目录,
扫不到时用下方 _BUILTIN 注册表直接导入编译进二进制的模块。

加载错误进 load_modes.errors,界面日志可见,不再静默。
"""

import glob
import importlib
import json
import os
import re
import sys
import traceback

from .base_mode import BaseMode

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES_DIR = os.path.join(BASE_DIR, "modes")
DEFS_DIR = os.path.join(BASE_DIR, "mode_defs")

_EXT_OK = (".py", ".pyd", ".pyc", ".so")

_PLATFORM_ORDER = [
    "douyin", "kuaishou", "shipinhao", "xiaohongshu",
    "tk", "baijia", "bili", "duoduo",
]

# 与原二进制直接取证的 8 组键值一致(值都带「处理」后缀)
PLATFORM_LABELS = {
    "douyin": "抖音处理",
    "kuaishou": "快手处理",
    "shipinhao": "视频号处理",
    "xiaohongshu": "小红书处理",
    "tk": "TK处理",
    "baijia": "百家处理",
    "bili": "哔哩处理",
    "duoduo": "多多处理",
}

# 打包后兜底:文件扫描为空时直接导入这些编译进二进制的模块
_BUILTIN = [
    ("douyin", "mode_feimao09284"),
    ("douyin", "mode_tongyao0921"),
    ("douyin", "mode_zhandou0921"),
    ("douyin", "mode_yunqi_qilin"),
    ("kuaishou", "mode_binfeng_caishen0923"),
    ("kuaishou", "mode_silie0921"),
    ("shipinhao", "mode_heimao_luoyue"),
    ("shipinhao", "mode_qixia_mode5"),
    ("shipinhao", "mode_caishen0923"),
    ("shipinhao", "mode_tianjia0923"),
    ("shipinhao", "mode_liuying_v15"),
    ("xiaohongshu", "mode_caima0924"),
    ("xiaohongshu", "mode_pianpian0924"),
    ("xiaohongshu", "mode_shuanggui0924"),
    ("xiaohongshu", "mode_yanjingshe0928"),
]

# mode_defs 的 json 里允许覆盖的字段
_DEF_FIELDS = (
    "name", "platform", "needs_aux", "gpu_supported", "help_text", "help", "heip",
    "notice", "announcement", "gonggao", "desc", "description",
    "output_suffix", "ext", "size", "fps", "bitrate", "hwaccel",
    "mix_seconds", "pip_scale", "margin",
    "command", "gpu_command", "expected_audio_tracks", "output_naming",
)


def platform_title_from_key(platform_key, mode_id=None):
    """平台键 -> 界面显示名。未知平台按 <键>处理 兜底,空则「未分组」。"""
    key = str(platform_key or mode_id or "").strip()
    if not key:
        return "未分组"
    if key in PLATFORM_LABELS:
        return PLATFORM_LABELS[key]
    if key.endswith("处理"):
        return key
    return key + "处理"


def _pkey_order(title, pkey):
    """平台排序:按 _PLATFORM_ORDER,不在表里的排最后。"""
    try:
        return _PLATFORM_ORDER.index(pkey)
    except ValueError:
        return len(_PLATFORM_ORDER)


def _mode_sort_key(modname):
    """按入口文件名里的数字编号排序(倒序: 数字大的在上面)

    mode_dy2.py 在 mode_dy1.py 上面,默认选中第一个(编号最大的新建模式)
    文件名没数字的(mode_default.py 等)编号按 0 算,排在最后
    """
    match = re.search(r"(\d+)\s*$", str(modname or ""))
    return -int(match.group(1)) if match else 0


def mode_order_key(mode):
    """同一平台下拉框内的排序:default 优先,其余按尾部数字倒序。

    对应原版 App._mode_order_key。
    """
    base = str(getattr(mode, "id", "") or getattr(mode, "name", "") or "").strip()
    match = re.search(r"(\d+)$", base)
    return (int(getattr(mode, "sort_priority", 0)),
            0 if base.endswith("default") else 1,
            -int(match.group(1)) if match else 0)


class DefMode(BaseMode):
    """mode_defs 里有 json、但本地没有对应 mode_*.py 时使用的通用模式。

    对应原版 main.py 的 RemoteServerMode
    (docstring:「宝塔新增但客户端本地没有 mode_*.py 时使用的通用模式。」)。
    """

    def __init__(self, mode_id, name, platform, needs_aux=False,
                 gpu_supported=False, help_text="", **fields):
        self.id = mode_id
        stem = str(mode_id).rsplit("/", 1)[-1]
        self._stem = re.sub(r"[^a-zA-Z0-9_]+", "_", stem)
        self._remote = True
        self._modname = "mode_" + self._stem

        self.name = name or stem
        self.platform = platform
        self.needs_aux = bool(needs_aux)
        self.gpu_supported = bool(gpu_supported)
        self.help_text = help_text or ""

        for key, value in fields.items():
            if value is not None:
                setattr(self, key, value)


def _instantiate(obj):
    """MODE 可以是类(常规)也可以是实例;统一返回实例。"""
    if isinstance(obj, type):
        if not issubclass(obj, BaseMode):
            return None
        return obj()
    if isinstance(obj, BaseMode):
        return obj
    return None


def _apply_def(mode, data):
    """把 mode_defs 的 json 字段合并到模式实例上(只覆盖 json 里写了的值)。"""
    for key in _DEF_FIELDS:
        if key in data and data[key] is not None:
            setattr(mode, key, data[key])
    if not getattr(mode, "id", ""):
        mode.id = str(data.get("id") or "")
    return mode


def _load_defs(errors):
    """读 mode_defs/<平台>/*.json,返回 {平台键: {通道: {字段}}}。"""
    defs = {}
    if not os.path.isdir(DEFS_DIR):
        return defs
    for pkey in sorted(os.listdir(DEFS_DIR)):
        if pkey.startswith("__"):
            continue
        pdir = os.path.join(DEFS_DIR, pkey)
        if not os.path.isdir(pdir):
            continue
        for path in sorted(glob.glob(os.path.join(pdir, "*.json"))):
            chan = os.path.splitext(os.path.basename(path))[0]
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ValueError("顶层不是 JSON 对象")
            except Exception as exc:
                errors.append("mode_defs/%s/%s.json 读取失败: %s: %s"
                              % (pkey, chan, type(exc).__name__, exc))
                continue
            data.setdefault("id", "%s/%s" % (pkey, chan))
            data["platform"] = data.get("platform") or pkey
            defs.setdefault(pkey, {})[chan] = data
    return defs


def _add_local_modes(errors, loaded_ids):
    """扫 modes/<平台>/mode_*.py,返回 {平台键: [mode实例]}。

    每个 mode_*.py 里要暴露 MODE = ModeXxx(BaseMode)。
    """
    groups = {}
    for pkey in sorted(os.listdir(MODES_DIR)) if os.path.isdir(MODES_DIR) else []:
        if pkey.startswith("__") or not os.path.isdir(os.path.join(MODES_DIR, pkey)):
            continue
        for path in sorted(glob.glob(os.path.join(MODES_DIR, pkey, "mode_*"))):
            modname, ext = os.path.splitext(os.path.basename(path))
            if ext not in _EXT_OK:
                continue
            if modname.endswith("_worker"):
                continue
            try:
                module = importlib.import_module("modes.%s.%s" % (pkey, modname))
                mode = _instantiate(getattr(module, "MODE", None))
                if mode is None:
                    errors.append("%s/%s: 未找到有效的 MODE 实例,已跳过" % (pkey, modname))
                    continue

                if not getattr(mode, "id", ""):
                    mode.id = "%s/%s" % (pkey, modname[len("mode_"):])
                if not getattr(mode, "platform", ""):
                    mode.platform = pkey
                if mode.id in loaded_ids:
                    errors.append("%s/%s: id %s 重复,已跳过" % (pkey, modname, mode.id))
                    continue
                loaded_ids.add(mode.id)
                groups.setdefault(pkey, []).append(mode)
            except Exception:
                errors.append("%s/%s 加载失败:\n%s" % (pkey, modname, traceback.format_exc()))
    return groups


def _add_builtin_modes(errors, loaded_ids):
    """内置注册表兜底,只在本地既没有 mode_*.py 也没有 mode_defs 时才走。

    这条路的用途是 Nuitka/打包后 .py 源文件不在 exe 旁的情形。
    本地源码版全部模式都由 mode_defs 提供,不该走这里,更不该在这里刷错误 ——
    平台目录是空的很正常,那不是加载失败。
    """
    groups = {}
    for pkey, modname in _BUILTIN:
        try:
            module = importlib.import_module("modes.%s.%s" % (pkey, modname))
        except ImportError:
            continue
        except Exception:
            errors.append("内置注册表 %s/%s 加载失败:\n%s"
                          % (pkey, modname, traceback.format_exc()))
            continue
        try:
            mode = _instantiate(getattr(module, "MODE", None))
            if mode is None:
                continue
            if not getattr(mode, "id", ""):
                mode.id = "%s/%s" % (pkey, modname[len("mode_"):])
            if mode.id in loaded_ids:
                continue
            mode.platform = getattr(mode, "platform", "") or pkey
            loaded_ids.add(mode.id)
            groups.setdefault(pkey, []).append(mode)
        except Exception:
            errors.append("内置注册表 %s/%s 加载失败:\n%s"
                          % (pkey, modname, traceback.format_exc()))
    return groups


def load_modes():
    """返回: {平台显示名: [mode实例, ...]} (平台与通道顺序固定)

    - 本地 mode_*.py 提供特殊参数逻辑,其字段可被同名 json 覆盖
    - 只有 json 没有 py 的通道,自动生成 DefMode 通用模式
    - 错误明细存 load_modes.errors(界面展示)
    """
    load_modes.errors = []
    errors = load_modes.errors
    loaded_ids = set()

    groups = _add_local_modes(errors, loaded_ids)
    if not groups:
        groups = _add_builtin_modes(errors, loaded_ids)
    defs = _load_defs(errors)

    # 把 json 定义合并进来:同 id 的覆盖字段,缺的补一个通用模式
    by_id = {}
    for modes in groups.values():
        for mode in modes:
            by_id[getattr(mode, "id", "")] = mode

    for pkey, channels in defs.items():
        for chan, data in channels.items():
            mode_id = data["id"]
            existing = by_id.get(mode_id)
            if existing is not None:
                _apply_def(existing, data)
                continue

            mode = DefMode(
                mode_id,
                data.get("name") or chan,
                data.get("platform") or pkey,
                needs_aux=data.get("needs_aux", False),
                gpu_supported=data.get("gpu_supported", False),
                help_text=data.get("help_text") or data.get("desc") or "",
            )
            _apply_def(mode, data)
            loaded_ids.add(mode_id)
            by_id[mode_id] = mode
            groups.setdefault(pkey, []).append(mode)

    # 组内排序 + 平台排序
    titles = {}
    for pkey, modes in groups.items():
        modes.sort(key=mode_order_key)
        titles[platform_title_from_key(pkey)] = pkey

    ordered = {}
    for title, pkey in sorted(titles.items(), key=lambda kv: _pkey_order(kv[0], kv[1])):
        ordered[title] = groups[pkey]

    if not ordered:
        errors.append("没有加载到任何处理模式:请检查 mode_defs/ 目录是否完整")
    return ordered


load_modes.errors = []

__all__ = [
    "load_modes", "BaseMode", "DefMode", "PLATFORM_LABELS", "platform_title_from_key",
    "mode_order_key", "_PLATFORM_ORDER",
]
