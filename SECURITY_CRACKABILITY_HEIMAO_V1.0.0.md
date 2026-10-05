# 黑猫@视频软件 V1.0.0 可破解性评估

评估对象：`dist-protected/黑猫@视频软件_V1.0.0`

评估日期：2026-10-05

方法：只读。不修改发布包、不生成破解版；只做静态识别 + 外部进程调用验证。

机器可读证据：`tools/heimao-v1.0.0-probe.json`

---

## 结论

**保护强度：低—中。当前版本对“直接复用算法”几乎不设防，对“静态反编译主程序源码”只有中等的延缓作用。**

两道保护（SProtect 主 EXE + VMProtect 核心 `.pyd`）都只提高了“读源码”的成本，**没有建立任何运行时授权信任边界**：

1. 发布版**没有卡密门禁**。`main.py` 明写“本地运行，不再依赖授权服务器”；`engine/auth.py` 的门禁函数 `local_gate()` 一律放行、`get_task_scope()` 恒返回 `None`；`app/license.py` 整套卡密 UI 是**死代码**，GUI 里没有任何地方引用它（`grep LicenseDialog|LicenseClient` 在 `app/` 下除 `license.py` 外零命中）。
2. 两个核心算法模块是**标准 CPython 3.9 扩展**，用任意 Python 3.9 x64 即可在启动器之外 `import` 并调用。VMProtect 的 `.vmp0` 段只保护了函数体实现，**不阻止黑盒查询**。

所以“别人破解了你的软件”这件事，最可能的形态是**直接拿走/换品牌/转卖/嵌进自己的壳**，而不是“写出注册机”——因为本来就没有需要绕过的注册逻辑。

---

## 已验证证据

### 1. 主 EXE 确实被 SProtect 加固

- 入口 RVA `0x82f5050`；`.text/.data/.rdata/.pdata/.xdata/.idata` 等节 `raw_size = 0`（已被搬走或抹平）。
- 真实载荷在 `.pyne` 节：53,004,800 字节，熵 ≈ 7.891（近似加壳/压缩）。
- 导入表被精简为 `KERNEL32.dll / msvcrt.dll / SHELL32.dll / USER32.dll / python39.dll`。
- 随包 `黑猫@视频软件_V1.0.0.exe.sp`（v2）与 `黑猫@视频软件_V1.0.0.exe.lic` 说明构建时走了 SProtect。
- SHA256 = `07addcdc…4797d8`，与 `manifest.json` 记录一致；`manifest.sig` 用 `core/release_integrity.py` 的公钥**验签通过**。
- Authenticode 状态：**NotSigned**。

结论：静态反编译主 EXE 的 Python 字节码成本较高。但**这条线不是攻击者需要的**——因为算法和门禁都不在 EXE 里强制执行。

### 2. 两个核心 `.pyd` 都被 VMProtect Ultra 保护

| 模块 | 大小 | `.vmp0` 大小 | `.vmp0` 熵 | 是否进 manifest |
| --- | --- | --- | --- | --- |
| `app/_flowcut_core.pyd` | 9,030,144 | 8,758,272 | 7.858 | 是 |
| `app/_random_frame_swap_core.pyd` | 2,863,104 | 2,801,664 | 7.283 | **否** |

两个模块的导出全部可用（`_flowcut_core` 14 个算法函数 + `_random_frame_swap_core` 3 个），且都只依赖 `python39.dll` 与 CRT，**运行时不需要主 EXE、不需要 manifest 验签、不需要授权服务器**。

### 3. 外部进程实测可导入并调用

用本机 `CPython 3.9`、`python -I`（隔离模式，不继承环境），`sys.path` 只指向发布目录，不启动主 EXE：

```
app._flowcut_core           -> 导入成功 (exit 0)
app._random_frame_swap_core -> 导入成功 (exit 0)
```

并对以下调用取得了真实返回值：

```
playback_rate(0.9, 1.1, 12345)   = 0.9833239745090683
filter_segments(5, 12345)        = [晴川, 胶片, 广川(乱码显示), ...]  # 5 个滤镜名
liuying_seed(1003, 2)            = 210461
shuffled_order(8, 12345)         = [3, 1, 7, 4, 2, 0, 5, 6]
filter_graph()                   = 265 字符完整 FFmpeg filter graph
liuying_video_filter(1003)       -> 含 1 个 perspective= 滤镜
mask_alpha(1080,1920,20,.05,0)   -> 70 字符 geq alpha 表达式
```

**这证明 VMProtect 只挡住了“读实现”，没挡住“黑盒查询 / 批量采样 / 直接复用”。** 带 `seed` 参数的函数（`playback_rate`、`filter_segments`、`shuffled_order`、`liuying_seed` 等）输出完全可复现，攻击者可以离线枚举出全部行为，甚至不需要反编译。

### 4. 发布清单覆盖面过窄

`manifest.json` 只有两条：

```
黑猫@视频软件_V1.0.0.exe
app/_flowcut_core.pyd
```

未被覆盖、可在不触发验签失败的前提下被替换/篡改的同产品文件包括：

- `app/_random_frame_swap_core.pyd`（一条完整算法线）
- `config.json`、`client/config.json`
- `mode_defs/**`（8 个渠道 × 3 档参数）
- `modes/douyin/*`（feimao 的 ffargs / filter_complex / metadata）
- `配置文件/参数预设/*.json`
- `ffmpeg.exe` / `ffprobe.exe`

另外，发布目录 `app/` **没有 `__init__.py`**，是隐式命名空间包。

---

## 关键问题（按优先级）

### P0 — 发布版没有授权门禁

`engine/auth.py::local_gate()` 恒返回 `None`（放行），`get_task_scope()` 恒返回 `None`；`main.py` 注释明确“不再依赖授权服务器”。发布出去之后，客户在**任何设备、任何时间、任意次数**都能完整运行，没有到期、没有设备绑定、没有任务令牌。

### P0 — 核心 `.pyd` 可脱离主程序独立使用

算法模块的调用路径不经过主 EXE 的 SProtect，也不经过 `verify_release_manifest()`。攻击者只需一个配对的 CPython 3.9，就能把 `app/_flowcut_core.pyd`（及 `_random_frame_swap_core.pyd`）当普通 Python 扩展调用、采样、封装进自己的程序。

### P1 — 发布清单不完整

见上节。`_random_frame_swap_core.pyd` 和其他所有配置/数据文件都不受完整性保护，可被替换而不报错。

### P1 — 发布物无法由当前工作树复现

- 发布版 `app/_flowcut_core.pyd` **不含** `qilin_pipeline_plan`、`liuying_*_1004` 这类新函数；
- 而当前 `native_src/flowcut_core.pyx` 已包含它们，`engine/native_core.py` 的 `_REQUIRED` 也要求 `qilin_pipeline_plan`；
- 工作区里重建的 `_flowcut_core.pyd`（9,736,704 字节）与发布版（9,030,144 字节）是**两个不同构建**。

即：当前 HEAD 打不出这个 V1.0.0 包，容易造成“修了但没修到发布物”或误签。

### P2 — 未做 Authenticode 签名

主 EXE `NotSigned`。不直接导致算法泄露，但用户无法借 Windows 验证发行者，假安装包更容易冒充。

---

## 修复顺序

按性价比从高到低：

1. **先决定要不要门禁。** 如果产品要收费/限时/限设备，就必须有一个真正的运行时门禁，且门禁要**在算法调用路径上生效**（推荐放在 `engine/auth.py::check()`，它是引擎侧唯一门禁入口，接入服务器零改动）。当前 `local_gate` 放行等于没有锁。
2. **把必须保密的算法搬到服务端**，客户端只拿“短期 + 绑定设备 + 绑定任务参数摘要 + 很短过期时间”的结果或参数。客户端本地 VMProtect 只能延缓，建立不了信任边界。
3. **如果必须离线**：在每个核心 `.pyd` 内部的导出函数入口做授权校验（不要只在主 EXE 检查），令牌用 `SERVER_PUBLIC_KEY` 同款 Ed25519 验签，并绑定设备指纹 + 参数哈希。
4. **收紧 Cython 导出面**：现在直接导出了 `qilin_pipeline_plan`、`filter_graph`、`mild_voice_filters` 这类高层计划函数和完整 FFmpeg filter graph，等于把配方直接给了。改成窄粒度、有状态、经授权的执行函数。
5. **发布清单覆盖所有产品自有文件**：`*.exe / app/*.pyd / config.json / mode_defs/** / modes/** / client/**`，并在 CI 里“产品模块存在但未进清单”就拒绝发布。
6. **统一构建**：由干净工作区 + 固定 Python/工具链生成可复现发布物，统一 `product_id`。
7. **给主 EXE 和安装包加 Authenticode 签名与时间戳。**

---

## 复现命令

```powershell
$py39 = "$env:LocalAppData\Programs\Python\Python39\python.exe"
python tools\probe_release_surface.py `
  "dist-protected\黑猫@视频软件_V1.0.0" `
  --python $py39 `
  --output "tools\heimao-v1.0.0-probe.json"
```

详细机器可读证据见 `tools/heimao-v1.0.0-probe.json`。
