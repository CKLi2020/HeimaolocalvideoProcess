# FlowCut 授权与程序保护

> **状态（YanJingwenhua 分支起）：服务器授权已移除。**
> 本文原先描述的一套方案（卡密登录 + 每任务令牌 + 编译模块内的算法门禁）
> 已不再随程序发布，其完整描述见 git 历史与本文件末尾的「历史方案」。
> 那些代码对应当前**已弃用**的授权服务 `https://yizhixiangsi.cn`；若该服务
> 仍在使用，其中的请求密钥应视为已泄露并轮换。

## 现状

程序**无网络、无卡密**即可启动并出片。授权相关代码的去向：

| 资产 | 状态 | 说明 |
|---|---|---|
| `engine/auth.py` | **现行** | 授权缝。`mask_alpha` / `butterfly_plan` 的本地实现 |
| `app/license.py` | 休眠 | 产品代码已无任何导入；仅 `scripts/calibrate_flowcut_core.py` 还引用 |
| `app/_flowcut_core.pyd` | 不再打包 | 保留在仓库供对照，已从构建脚本移除 |
| `native_src/flowcut_core.pyx` | **保留** | 上述 `.pyd` 的 Cython 源码，是算法的权威规格 |
| `scripts/build_native.ps1` | 保留 | 单独可用；不再被 `build_protected.ps1` 调用 |

## 接入新授权服务器

引擎侧只需要改**一处**：在程序入口调用一次

```python
from engine import auth
auth.set_gate(lambda engine, job: None)   # 返回 False 或抛异常即拒绝
```

引擎内部唯一的门禁调用点是 `engine/worker.py` 的 `BatchWorker._run_batch`
（覆盖 hdh / 蝴蝶AB / 黑猫03 全部通道）。默认门禁 `auth.local_gate` 一律放行，
所以本地运行不受影响。

算法实现（`mask_alpha`、`butterfly_plan`）与授权无关，切换服务器时无需改动。

## 程序保护

发布仍走 `build_protected.bat`：Nuitka onefile 编译 + VMProtect Ultra 保护入口点，
输出到 `dist-protected\黑猫@苍狼_V<版本号>`。

**不再**打包 `app._flowcut_core.pyd` 与 `cryptography`——原先编译这些是为了
在原生模块内做算法门禁，该机制已随服务器授权一并移除。

成品视频保持标准 MP4，不使用参考项目的 `BCVIDEO1` 私有加密容器。

---

## 历史方案（已弃用，仅存档）

原方案经 `https://yizhixiangsi.cn/api/license/{activate,check}`：

- 请求：HTTPS + HMAC-SHA256 + 时间戳 + nonce
- 响应：Ed25519 公钥验签 + HMAC 校验
- 设备绑定：Windows MachineGuid 的 SHA-256 指纹
- 本地卡密：`%APPDATA%\BlackCatFlowCut\license.json`
- 每个处理批次申请最长 5 分钟的 Ed25519 签名任务令牌

`app\_flowcut_core.pyd` 内有六段逻辑用 VMProtect Ultra 标记虚拟化，且当时
没有 Python 回退：授权请求 HMAC 签名、Ed25519 响应验签、蒙版 Alpha/羽化表达式、
签名任务令牌及作用域校验，以及令牌授权后的蒙版表达式与蝴蝶AB 计划。

任务令牌绑定应用、通道、批次、输入数量、参数哈希、设备码、设备指纹与过期时间；
缺令牌、字段被替换、签名被改或令牌过期都会拒绝处理。

对应的服务端环境变量与请求密钥**不再记录于本文件**（见 git 历史）。
