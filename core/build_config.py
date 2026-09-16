"""配置层:内嵌默认值 + client/config.json 覆盖。

键名与内嵌默认值照反编译取证恢复(见 work/xiaohuamao-src-recover/)。
与原版的唯一行为差异是容错:原版 load_config 遇到坏 JSON 直接抛 JSONDecodeError
崩在启动路径上(crash.log: main.py line 139 load_config -> JSONDecodeError:
Extra data: line 1 column 18,紧随其后 KeyError: 'server_url'),
本地版改成记一条 warning 后退回内置默认值,并把缺失键补齐。
配置问题不该让程序打不开。
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_DIR = os.path.join(BASE_DIR, "client")
CONFIG_PATH = os.path.join(CLIENT_DIR, "config.json")

# 内嵌默认值。取自原二进制 core/build_config.py 的字符串常量。
EMBEDDED = {
    "app_title": "小花猫视频处理 V1.0",

    # 可执行文件。支持绝对路径,或相对 rebuild/ 的路径;
    # 找不到时会依次回退到 rebuild/bin/、原程序 bin/、系统 PATH(见 core.runner._resolve)。
    "ffmpeg_path": "bin/ffmpeg.exe",
    "ffprobe_path": "bin/ffprobe.exe",

    # 处理默认值
    "default_output_dir": "output",
    "default_threads": 6,
    "default_bitrate": "6000k",
    "default_gpu": True,
    "default_cpu": False,
    "default_nvenc": True,
    "gpu_hwaccel": True,
    "force_gpu_h264": False,

    # --- 以下键本地版不读取,仅为与原版 24 键 schema 对齐而保留 ---
    # 原版是瘦客户端,这些键服务于已下线的宝塔后端与第三方解析接口。
    # 保留它们是为了将来真要做联网版时字段名不用再猜一遍。
    "origin": "",
    "has_location": False,
    "server_url": "",          # 原: https://xknmb.zjwhcmxy.com/index.php
    "api_key": "",             # 原: CHANGE_ME_SECRET (开发占位符,非生产值)
    "token": "",
    "content_host": "",
    "parse_api_url": "",       # 原: https://syapi.chuangye.site/home/api
    "parse_api_key": "",
    "parse_api_uid": "",
    "parse_api_type": "",
    "parse_product_type": "",
}


def resolve_path(path):
    """把配置里的相对路径解析成绝对路径(相对 rebuild/ 根)。"""
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(BASE_DIR, path))


def load_config():
    """读取配置。有 client/config.json 就用它覆盖内置默认值,否则全用内置默认值。

    容错:文件坏掉/顶层不是对象/读不动,都退回内置默认值,不抛异常。
    警告明细存 load_config.warnings(界面日志可见,不静默)。
    """
    load_config.warnings = []
    cfg = dict(EMBEDDED)

    if not os.path.exists(CONFIG_PATH):
        load_config.warnings.append("未找到 client/config.json,使用内置默认配置")
        return cfg

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        if not isinstance(user, dict):
            raise ValueError("顶层不是 JSON 对象")
        # 逐键覆盖:未知键也收下(向前兼容);None 视为"没写",不覆盖默认值
        for key, value in user.items():
            if value is not None:
                cfg[key] = value
    except Exception as exc:
        load_config.warnings.append(
            "client/config.json 读取失败(%s: %s),已改用内置默认配置"
            % (type(exc).__name__, exc)
        )

    # 数值归一化:配置文件里写成字符串也能用
    for key in ("default_threads",):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = EMBEDDED[key]
            load_config.warnings.append("%s 不是整数,已用默认值 %s" % (key, EMBEDDED[key]))
    if cfg["default_threads"] < 1:
        cfg["default_threads"] = EMBEDDED["default_threads"]

    for key in ("default_gpu", "default_cpu", "default_nvenc", "gpu_hwaccel", "force_gpu_h264"):
        if not isinstance(cfg[key], bool):
            cfg[key] = bool(cfg[key])

    if not str(cfg.get("app_title") or "").strip():
        cfg["app_title"] = EMBEDDED["app_title"]

    return cfg


load_config.warnings = []
