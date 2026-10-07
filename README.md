# 黑猫@视频软件

本仓库以「月落@苍狼」的 `YanJingwenhua` 分支为唯一基础，在原界面和原有功能上增加了「03 本地视频处理」通道。

## 已整合功能

- 视频处理：支持主/辅视频文件或文件夹批处理，包含抖音、快手、视频号、小红书、TK、百家、哔哩和千川 8 类模式
- 抖音「云麒1004」通道已接入，单主视频输入，支持 CPU、NVIDIA 和 AMD 编码；按原工具特征逐次随机生成彩色几何网格、旋转网格、滤镜参数、抽帧点和音频扰动，不再使用纯白/纯黑占位素材，关键生成计划由受保护原生核提供。
- 云麒输出默认启用平台 SPS 兼容：2026-10-05 上传对照确认，将 FFmpeg 9 输出的 SPS 尾部复现为 FFmpeg 7 的形式后，平台播放全程正常；本地播放仍可能闪烁。该处理刻意保留非标准停止位，不是通用 HEVC 修复。工具按 MP4/HEVC 结构定位，仅修改已识别布局的一个字节，不改画面、音频或时间戳；布局判定和字节计算位于受保护原生核，未知布局明确报错，GPU 兼容失败自动重试 CPU。独立 worker 也执行同一处理，成功日志会明确提示非标准 SPS。显卡实际编码后的平台效果尚未验证，平台规则变化后应重新验证。
- 视频号「流萤」仅需选择主视频，辅助校验直接使用主视频，无需单独选择辅助视频。支持 1–100 份裂变：每个主视频逐份独立执行处理，输入 M 个视频、裂变 N 份，共生成 M × N 个产物；每份使用不同随机种子，避免随机画面重复。保留固定随机闪帧，额外随机画面增强关闭，界面不再提供该开关。
- 视频号新增「立梦1007」并置于列表首位，只需主视频，固定启用倒立且隐藏拉伸、融合、倒立三个效果选项，支持 1–100 份输出和 CPU/NVIDIA/AMD。
- 视频号「栖霞1007」原地对齐龙门闪灵 v2 的模式五，并置于「立梦1007」之后；保留 ID `shipinhao/qixia_mode5`、其他通道相对顺序和 1–100 份输出，只需主视频，融合自动使用同一主视频。拉伸、融合、倒立可组合，融合透明度范围 0–100%、默认 50%；拉伸保持取证确认的 BT.709/TV 信号，倒立保留像素翻转及显示矩阵。两个通道共享受保护的 `qixia_pipeline_plan`，CPU/NVIDIA/AMD 继续沿用服务的 GPU 失败后 CPU 回退。输出路径默认是各自工具根目录的 `output`，用户可选择或输入其他文件夹，不再限制在 `capture` 内；切换通道保留所选输出目录，不迁移或删除历史视频。取证文件仍归集到 `capture`。相同主辅样本的融合取证不证明不同素材的隐藏混合实现已完全复现，编码版本也会影响音频时长和 encoder 标签。
- 蒙版模式
- 素材拼接

栖霞1007可在源码或发布启动器内运行 `--qixia-self-test <含音频的主视频路径>`，
实际执行一次三开关全开、透明度 25% 的 CPU 转换并检查 UI 到 worker 的设置传递、
通道注册、日期名称、视频号排序与可选输出文件夹。自检视频写到该工具的
`output\qixia-self-test`，`qixia-self-test.json` 仍写到该工具的 `capture`；

立梦1007可在源码或发布启动器内运行 `--limeng-self-test <含音频的主视频路径>`，
实际执行一次固定倒立的 CPU 转换并检查隐藏效果设置、栖霞1007并存、通道注册、
视频号首位排序与可选输出文件夹。自检视频写到该工具的
`output\limeng-self-test`，`limeng-self-test.json` 仍写到该工具的 `capture`；
这是会处理视频的检查，应仅使用已授权样本。发布版必须用自己的 EXE 运行，
不能在外部 Python 进程中调用启用了宿主门禁的核心代替验收。

## 源码启动

## 一、怎么跑

| 场景 | 做什么 |
|---|---|
| 第一次用（新机器） | 双击 **`安装.bat`** —— 建 `.venv`、装 customtkinter、准备 `bin\` 中的 FFmpeg |
| 日常使用 | 双击 **`启动.bat`** |
| 出错要看堆栈 | 双击 **`启动-调试.bat`**（保留控制台） |
| 改完代码验证 | 双击 **`自检.bat`**（几十秒，退出码 0 = 全过） |

启动**没有任何登录 / 卡密 / 联网环节**，直接进主界面。

安装时优先复用 `..\bin` 中的 `ffmpeg.exe`/`ffprobe.exe`；找不到时，脚本会从 gyan.dev 下载并解压
FFmpeg essentials 到本地 `bin\`。换 ffmpeg 就把新的丢进 `..\bin\` 或 `bin\`，也可以在
`client/config.json` 里改 `ffmpeg_path`。

---

## 二、目录结构与职责

```
rebuild/
├── 启动.bat / 启动-调试.bat / 安装.bat / 自检.bat
├── main.py                  GUI（customtkinter）+ 批处理 worker
├── selftest.py              端到端自检，8 组检查
├── core/
│   ├── build_config.py      EMBEDDED 默认值 + client/config.json 覆盖（容错坏 JSON）
│   ├── hardware.py          显卡探测 / 可用编码器 / 编码器自检
│   └── runner.py            ffmpeg 执行：argv 拆分、进度、整树强杀、产物校验
├── modes/
│   ├── base_mode.py         BaseMode + build_params + render（模板渲染）
│   ├── __init__.py          load_modes：扫 py + json，合并成 {平台: [模式]}
│   └── <平台>/              放 mode_*.py 时才需要；现在是空的
├── mode_defs/<平台>/        模式定义 json（命令模板在这里，团队改参数只动这里）
├── client/config.json       用户配置
└── bin/  →  ../bin          复用原 ffmpeg
```

数据流：

```
界面状态 ──> BaseMode.build_params()  ──> {占位符: 值}
                                          │
mode_defs/<平台>/<通道>.json 的 command ──┴─> render() ──> 命令字符串
                                                             │
                                              FFmpegRunner.run() ──> 产物
                                                             │
                                                   verify_output() 单轨断言
```powershell
python -m pip install -r requirements.txt
python main.py
```

FFmpeg/FFprobe 会按 `client/config.json` 配置和程序根目录自动查找。

## 受保护版打包

按原 `YanJingwenhua` 流程执行：

```powershell
scripts\build\_protected.bat
```

打包脚本已包含新增的 `core`、`modes`、`mode_defs` 和 `client` 资源。如需交给 SProtect 处理，再执行：

> **⚠️ 更正（2026-09-16）**：本节原先写"原版 `output/` 两个产物是坏的多轨 MP4，疑似 GPU→CPU
> 重试写了同一文件"。**该结论已证伪。** 那两个文件不是 `小花猫 .exe` 产物，而是一个本地脚本
> `yuying_ab_worker.ps1` 的产物：文件里三个 `udta/name` box 逐字写着
> `Platform_Source(A)`（源视频，copy）、`Local_Display(B)`（x264 重编码）、
> `Silent_Market_6_8H`（8000 Hz aac，时长 22055 s），正是该脚本
> `-metadata:s:v:0/v:1`、`-metadata:s:a:N` 的字面量。所以"4 条流""22055 秒"是那个脚本的
> **设计输出**，不是原版缺陷。**别再据它推断原版行为。**
>
> 下方三条防护因此**不是"修原版缺陷"，而是本重写自身的产物完整性保障** —— 与上面的更正无关，
> 依然值得保留：

1. **写临时文件 + 成功后原子改名** —— 每个产物先写 `<名字>.part.mp4`，校验通过才 `os.replace`
   成正式名。重试/中断留下的半成品永远不会顶替正式产物。

1. **写临时文件 + 成功后原子改名** —— 每个产物先写 `<名字>.part.mp4`，校验通过才 `os.replace`
   成正式名。重试/中断留下的半成品永远不会顶替正式产物。
2. **每次尝试前先删临时文件**（全程 `-y`，绝不追加）。
3. **收尾断言 `verify_output()`** —— ffprobe 校验"恰好 1 视频轨 + 最多 1 音轨 + 时长为正"。
   不合格就**丢掉产物并记为失败**：宁可少一个，也不交付播不动的文件。

第 3 条现在就是回归测试：`自检.bat` 每次都会断言所有产物单轨。

另外两个修复：

- **GPU 模板与参数错配**：`render(use_gpu=True)` 选了 GPU 模板、`build_params` 却按过期的
  `state['use_gpu']` 算参数，把 CPU 的兜底字面量 `-hwaccel processor` 塞进 GPU 模板，
  ffmpeg 报 `Unrecognized hwaccel`。现在 `render()` 会把生效的 `use_gpu` 写回 state。
- **坏 JSON 不再让程序打不开**：原版 `crash.log` 显示它死在
  `main.py line 139 load_config` → `JSONDecodeError: Extra data` → `KeyError: 'server_url'`，
  即配置文件一坏，程序直接起不来。现在读不动就退回内置默认值并记一条日志。

---

## 五、刻意的差异（都不是遗漏）

| 差异 | 原因 |
|---|---|
| 无登录 / 卡密 / 联网 | 卡密是第三方 MapoLicensor 云（`licvip1.maposafe.com`），不是公司自有代码，属第三方商业 DRM，不重写也不绕过 |
| 不做 `overrideredirect` 自绘标题栏 | 原版为此写了十来个方法对抗 Windows 贴边/缩放/DPI。v1 用系统标准边框，代码量少一个数量级，也不会在各版本 Windows 上碎。要加回来：那批方法名（`_apply_window_chrome` / `_drag_window` / `_get_work_area` …）就是清单 |
| 处理日志显示**明文**命令 | 原版日志标题是「命令经AES加密下发,不显示明文」——因为命令来自服务器。本地版命令就在 `mode_defs` 里，藏着只妨碍排障 |
| 公告用静态条，不做跑马灯 | 跑马灯要常驻 `after()` 循环，收益只是观感 |
| 处理方式用**一个下拉框** | 原版同时给了「处理模式下拉框」+「GPU/CPU 勾选框」两套等价控件，冗余且可能互相矛盾 |
| 辅视频行**只置灰、不清空** | 清空会把已选好的辅视频弄丢，切走再切回来得重选 |

保留了原码的错别字：`不可用，已自効切到CPU处理` 的「自効」、
`_mode_help_from_item` 的取值顺序 `help → heip → notice → announcement → gonggao → desc → description`
（`heip` 就是错别字，保留是因为团队的模式 json 里可能真写了这个键）。

---

## 六、没做的部分

- **通用解析下载区**（原版侧栏有这个入口）——原实现依赖第三方付费解析接口
  `syapi.chuangye.site`。替代方案是 yt-dlp，但它对视频号基本无解、小红书/快手时好时坏，
  所以本轮不做。`main.py._build_sidebar` 里留了扩展点注释，
  `requirements.txt` 里 yt-dlp/Pillow 也留着注释行。
- **宝塔后端协议**（`core/server_api.py` / `aes.py` / `ecdh.py`）——已下线，只存档不重写。
- **原版的 `core/guard.py`（反抓包拦截）和命令隐藏**（ADS 备用数据流 + 覆写子进程命令行）——
  本地化后没有存在意义。

---

## 七、规格的来源：哪些是确证的，哪些是重建的

**直接从二进制取证（可靠）**：模块清单、24 键配置 schema 与内嵌默认值、8 平台中英文映射、
模式 id 命名法（`mode_<通道>.py` ⇄ `<通道>.json.php`，`id = "<平台>/<通道>"`）、
`BaseMode.build_params` 的签名与返回键名、`FFmpegRunner` 的 argv 拆分方式
（`shlex.split(posix=False)`，为保住滤镜里的单引号）、三条进度正则、
硬件探测顺序与编码器映射、排序规则、界面中文文案表、`RemoteServerMode` 的存在与用途。

**重建（`RECONSTRUCTED`，需按业务调整）**：ffmpeg 命令模板本体、模式定义内容、
控件精确坐标。模板是照恢复出的语义 + 实测产物尺寸反推的，**画质参数请按实际业务调**。

**环境**：Python 3.x、customtkinter 6.0.0；`安装.bat` 会从 gyan.dev 准备
`bin/ffmpeg.exe` 和 `bin/ffprobe.exe`。
```powershell
scripts\finalize_sprotect_release.bat
```
