# FlowCut 授权与程序保护

> **状态（Heimao 分支，2026-10-05 起）：算法已重新纳入授权。**
> 旧的服务器方案（卡密登录 + 每任务令牌 + HMAC 请求）仍然废弃，见 git 历史与
> 文末「历史方案」；对应服务 `https://yizhixiangsi.cn` 已下线，其中的请求密钥
> 视为已泄露。
>
> 现行保护是两层：
>
> 1. **启动器**：SProtect 加壳 + 联网 `NetVerify`（到期、设备），管 EXE 本身。
> 2. **算法**：两颗 `.pyd` 都经 VMProtect Ultra 虚拟化并挂上同一道宿主门禁 ——
>    `app/_flowcut_core.pyd`（14 个 `FCALGO:*` 标记）与
>    `app/_random_frame_swap_core.pyd`（3 个 `RFCORE:*` 标记）。每个导出函数入口
>    先确认自己运行在**发布启动器进程内**：宿主可执行文件必须与该 `.pyd` 同处一个
>    发布根目录。从任意 CPython 3.9 旁加载这些 `.pyd` 只能 import，**一调用就直接
>    结束进程**（退出码 `0x46434731`，ASCII "FCG1"）——这正是 V1.0.0 被拿走后可以
>    直接 import 并出片的那个洞。
>
> 因此**发布流程与用户侧都没有变化**：不发序列号、不发 `license.key`、不联网、
> 不做卡密。判定只看「我是不是跑在自己的发布目录里」，全部离线。
>
> 这一层挡的是实测到的攻击形态（裸解释器旁加载），不是密码学证明：把 `.pyd`
> 拷进别人的程序、再补一个同名目录结构的可执行文件仍可绕过。整个发布目录被拷走
> 的情况不靠这里，由启动器自身的 SProtect 联网授权负责。要更强的绑定
> （把宿主 EXE 的 SHA-256 对到签名清单上）见下文「算法门禁怎么工作、边界在哪」。

## 现状

授权相关资产去向：

| 资产 | 状态 | 说明 |
|---|---|---|
| `engine/auth.py` | **现行** | 授权缝。`mask_alpha` / `butterfly_plan` 的本地实现 |
| `app/_flowcut_core.pyd` | **现行，已打包** | VMProtect Ultra + 宿主机门禁；由 `scripts/build_native.ps1 -LicenseGate` 产出，gitignore 的构建产物 |
| `app/_random_frame_swap_core.pyd` | **现行，已打包** | 爆闪渠道的核心，同上加壳加门禁；现在也由源码产出，gitignore 的构建产物 |
| `native_src/flowcut_core.pyx` | **保留** | 上述 `.pyd` 的 Cython 源码，是算法的权威规格 |
| `native_src/random_frame_swap_core.pyx` | **保留** | 爆闪核心的 Cython 源码，与 `modes/shipinhao/heimao_luoyue_core.py` 逐位对拍通过 |
| `engine/native_core.py::RANDOM_SWAP_REQUIRED` | **现行** | 两颗核心「发布版必须导出哪些符号」的唯一声明处，构建与验签两侧都读它 |
| `scripts/build_native.ps1` | **现行** | 被 `build_protected.ps1` 调用；一次产出两颗 `.pyd`，`-LicenseGate` 打开算法门禁 |
| `docs/archive/make_vmprotect_keys.py` | 已归档 | 原 `scripts/make_vmprotect_keys.py`；「一人一码」方案已放弃，无调用方 |
| `docs/archive/make_license_serial.py` | 已归档 | 原 `scripts/make_license_serial.py`；同上 |
| `docs/archive/license.py` | 已归档 | 原 `app/license.py`。硬编码密钥已随源码公开，不可复用 |
| `docs/archive/calibrate_flowcut_core.py` | 已归档 | 原 `scripts/calibrate_flowcut_core.py`；依赖的服务与 `app/license.py` 均已下线，跑不起来 |
| `docs/calibration/*.json` | **现行** | 纯本地等价实现的回归基准，测试直接读它，不需要上面那个脚本 |
| `modes/shipinhao/heimao_luoyue_core.py` | 待删除 | 明文等价实现，只能留在源码树做对照；发布路径必须 fail closed |
| `modes/douyin/feimao_recipe.py` | **现行，已编译** | 飞猫/听雪通道的 ffmpeg 配方（滤镜图 + 12 项参数）。由 `--include-package=modes` 编译进启动器，发布包里没有可读副本 |

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

发布三步，前两步在构建机、第三步是离线 GUI 交接：

1. `build_protected.bat` → `scripts\build_protected.ps1`
   先用 `-LicenseGate` 编译并 VMProtect 保护 `app\_flowcut_core.pyd` 与
   `app\_random_frame_swap_core.pyd` 两颗核心，再 Nuitka `--standalone` 出
   `dist-protected\<产品名>_V<版本>\`。
   不需要任何密钥 / 序列号参数（门禁不用 VMProtect 授权系统，见下）。
   `--nofollow-import-to=modes.shipinhao.heimao_luoyue_core` 保证明文等价实现
   不进包。
2. 用 SProtect 打开该目录里的启动器，把加壳结果存成同名的 `.sp.exe`。
3. `finalize_sprotect_release.bat` → `scripts\finalize_sprotect_release.ps1`
   换入加壳启动器、重签清单、写 `SHA256SUMS.txt`。
   需要环境变量 `BLACKCAT_RELEASE_KEY_PASSWORD`（签名私钥口令），且会拒绝
   未加密的、或位于仓库内的签名私钥。

### 算法门禁怎么工作、边界在哪

两颗核心的 `.pyx`（`native_src/flowcut_core.pyx`、`native_src/random_frame_swap_core.pyx`）
各带一份相同的 `_ensure_host()`，在每个导出函数入口调用。原生侧 `fc_host_ok()` 用
`GetModuleHandleExW` 从自己的代码地址取本 `.pyd` 的路径、用 `GetModuleFileNameW(NULL)`
取当前进程映像，两者都来自操作系统，Python 层 monkeypatch `sys` / `os` 影响不了。
判定就是两者「上两级目录是否相同」，即 `<发布根>\app\<核心>.pyd` 与
`<发布根>\<启动器>.exe`。

判定通过就直接返回；不通过调 `fc_host_deny()`，即 `ExitProcess(0x46434731)`，
**整个拒绝过程不经过 Python**。

**为什么是结束进程而不是抛异常**（2026-10-05 实测，这条踩过坑）：同一份源码，
未加壳时 `raise` 任何异常都干净；一旦 VMProtect Ultra 虚拟化区域达到 14 个以上，
模块内的 Python 异常路径就会跑飞——要么访问越界，要么在 `mild_voice_filters`
的 f-string 拼接里触发 `PyUnicode_IS_READY` 断言。`PermissionError`、`ValueError`、
`RuntimeError`、自定义异常类、把 `raise` 挪到无标记的辅助函数里，全部失败；只有
2 个虚拟化区域时偶尔能过。所以拒绝改成纯 C 的 `ExitProcess`：不构造异常对象、
不写 traceback、不碰模块全局变量。也因此 `FCALGO:host.check` 这个标记被去掉了——
加上它正好凑成 15 个区域，必崩；现在是加固前的 14 个。爆闪核心只有 3 个区域，
离这个上限很远，但它的门禁同样不标记，两颗核心保持一致。

**不用 VMProtect 授权系统**，所以工程里没有 `<LicenseManager>`、没有 `PrivateExp`、
没有每客户序列号；`build_native.ps1` 也就不再需要任何密钥参数。

**能挡什么**：实测的攻击形态——拿系统里任意 CPython 3.9 把 `sys.path` 指到发布
目录，`import` 后直接调算法。现在 import 仍然成功（导出集检查依赖这一点），
但两颗核心共 17 个导出函数（14 + 3）**任意一个**被调用，进程立即以退出码
`0x46434731` 结束，无 traceback、无部分输出。

**挡不住什么**：把 `.pyd` 拷进自己的程序，并在程序自己的目录下摆一个可执行文件，
使「上两级目录相同」成立。这是刻意接受的取舍——真要防它，得把宿主 EXE 的
SHA-256 对到 `manifest.json` 的签名清单上（`cryptography` 已随包），代价是换发布
签名密钥时 `.pyd` 必须一起重建。当前没做。

**副作用（两处，都要知道）**：

1. 带门禁构建的算法冒烟测试在构建机上跑不了（构建机是 `python.exe`，不在发布
   目录里）。`build_native.ps1 -LicenseGate` 会为两颗核心各跳过它并打印提示，
   功能验证改为启动一次打好包的发布版。算法正确性本身仍由未开门禁的 dev 构建加
   `tests/test_local_mask_alpha.py` / `tests/test_butterfly_plan_parity.py` 保证；
   爆闪核心则由与明文等价实现的逐位对拍保证（见下）。
2. `-LicenseGate` 会把工作树里的 `app\_flowcut_core.pyd` 和
   `app\_random_frame_swap_core.pyd` 都换成门禁版，而它们是 gitignore 的本地产物。
   此后在本机直接调算法（含 `tests\test_qilin_core.py`，以及走爆闪频道的
   `tests\test_heimao_luoyue_channel.py`）会让解释器进程**直接退出**，看起来像
   "崩溃"。构建完发布包后，必须用不带 `-LicenseGate` 的 `build_native.ps1`
   再跑一次把工作树恢复成开发版。

### 爆闪核心的源码与对拍

`app/_random_frame_swap_core.pyd` 曾经是一个直接入库、又没有任何源码的二进制，
等于发布里放了一颗谁都无法重建、也无法审计的核心（加固计划的 2.E）。现在它和
flowcut 核心一样由 `native_src/random_frame_swap_core.pyx` 编译产出，并从 git
索引里摘出、改为 gitignore 的构建产物。

换核心前做过逐位对拍：新 pyx 的产物与它替换掉的旧二进制、以及明文等价实现
`modes/shipinhao/heimao_luoyue_core.py`，在 `filter_graph`（265 字符全等）、
99 组 `shuffled_order(count, seed)`、46 组 `special_offsets(durations, offsets)`
（含空表、长度不等、`±2^31` 边界）上全部相等。所以这次替换不改变爆闪频道的出片结果。

明文等价实现仍然只留在源码树里供对拍和调试；发布路径上
`mode_heimao_luoyue_worker.py` 一旦发现缺少受保护核心就 fail closed，
`build_release_manifest.py` 也会把明文实现列为 `FORBIDDEN`、发现即中止构建。

### 轮换发布签名密钥

签发密钥是发布信任的根：拿到私钥的人可以为任意构建签清单，而每个已安装的副本
都会接受。所以它必须加密、且不在仓库里。轮换步骤：

```powershell
python scripts\make_release_signing_key.py --out "%USERPROFILE%\.blackcat-release\manifest-private.pem"
# 把打印出的 _PUBLIC_KEY 字面量贴进 core\release_integrity.py，然后重新发布。
```

已经发出去的启动器里编译的是**旧**公钥，所以换密钥必须连带重发启动器；
`build_release_manifest.py` 会在签名前比对私钥与 `_PUBLIC_KEY`，对不上就中止，
避免签出一个客户端验不过的包。

### 清单覆盖

`build_release_manifest.py` 按 allowlist 遍历发布目录并逐个哈希，
`core\release_integrity.py` 在启动时（窗口出现前）全量复验，任一不符即拒绝启动。
没有进清单的产品自有文件等于没有保护，所以遍历刻意做宽。

刻意**不**进清单：`config.json` / `client/config.json`（每次启动重写）、第三方运行时
（PySide6/numpy 等约 1 GB）、用户工作目录（主视频/辅助视频/成品/模板/背景音乐）、
以及 311 MB 的 `使用教程（使用必看）` 视频。理由见脚本的模块 docstring。

清单里也**绝不能**出现 `modes/shipinhao/heimao_luoyue_core.py`（明文等价实现）；
脚本把它列为 `FORBIDDEN`，发现即中止构建。

### 通道配方必须编译进产物，不能当数据文件进包

15 个注册通道里只有 3 个（云麒1004 / 流萤1003 / 爆闪）把算法放进了 VMProtect
虚拟化核心；其余 12 个的算法随 `--include-package=modes` 编译进启动器，再被 SProtect
加壳。实测发布目录里没有 `.py`、没有 `.pyc`，启动器里对通道名、滤镜串的字符串搜索
零命中——**但前提是这些算法只以 Python 源码形态存在**。

唯一的例外曾是飞猫／听雪：它的滤镜图和 ffmpeg 参数被 `build_protected.ps1` 用
`--include-data-files` 白名单进包，等于把整张滤镜图（5098 字符，含 12 个 🐱 水印）
明文交给任何解压发布包的人。现已内联进 `modes/douyin/feimao_recipe.py` 的模块常量
`FILTER_GRAPH` / `FFARGS`，两个数据文件已从仓库删除。

因此有一条硬规则：**通道配方只能是编译进 `modes` 包的模块常量**，不得再用
`--include-data-files` 送进发布包。两侧都有护栏，任一侧发现这两个文件就中止：

- `build_release_manifest.py::FORBIDDEN`——签名前检查，命中即中止构建；
- `verify_release.py::PLAINTEXT_ALGORITHMS`——发布后自检，命中即报「发布物里有明文通道算法」。

两者是同一份清单，改动时必须同步。目前各四条：`heimao_luoyue_core.py` 及其
`__pycache__/*.pyc`，加 `filter_complex.txt`、`feimao_ffargs.json`。

`tests/test_feimao_yanjingshe_channels.py` 同时钉死了这条规则和滤镜图的保真度
（长度 5098、12 个 🐱、单行），防止它被悄悄挪回数据文件或被编码损坏。

唯一仍以文件形态进包的通道数据是 `modes/douyin/feimao_metadata.txt`（27 字节）：
ffmpeg 用 `-f ffmetadata -i <路径>` 读它，必须是真实文件；内容只泄露内部代号
`title=tingxue`，而且这个 title 会被 `-map_metadata` 写进成品 MP4，改动它等于改出片结果。

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
