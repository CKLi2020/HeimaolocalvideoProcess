# 黑猫视频处理软件 · 本地重写版

原 `小花猫 .exe` 的替代实现。原程序由离职工程师用 **Nuitka + MapoSafe SProtect64** 打包，
源码丢失且**无法反编译还原**（IDA 里只有 VM handler，不是 Python 源码）；
ffmpeg 命令模板不在客户端里，由服务器下发（`xknmb.zjwhcmxy.com`，2026-09-16 实测**仍在运行**）。

所以这不是"还原"，是**照恢复出的规格重写**一个等价的纯本地客户端：无卡密、无后端、双击即用。

> **关于原版的 ffmpeg 命令模板**：2026-09-16 已从运行中的原客户端把真实参数整条取回
> （值藏在 NTFS 备用数据流 `ffarg` 里，取证过程见
> `work/xiaohuamao-src-recover/evidence/E-008.md`）。
> 但其滤镜链的核心是**隔行交织 + 音频微量变速/噪声底 + 伪造元数据**，
> 用途是规避平台的重复内容/指纹识别，**不属于视频处理功能，未移植进本目录**。
> 本目录只做正当的归一化与转码。

---

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
```

---

## 三、加一个模式（团队最常用的操作）

**方式 A：只丢一个 json —— 够用，最省事**

往 `mode_defs/<平台>/` 丢一个 `<通道>.json`，重启程序，该平台下拉框自动多一项。
不用改任何 Python。空白模板：

```json
{
  "id": "douyin/my_channel",
  "name": "我的通道",
  "platform": "douyin",
  "needs_aux": false,
  "gpu_supported": true,
  "output_suffix": "_my",
  "ext": "mp4",
  "size": "720x1280",
  "fps": 30,
  "bitrate": "6000k",
  "desc": "这个模式干什么用的，会显示在日志里",
  "command":     "ffmpeg -y -hide_banner -i \"{input}\" -vf \"scale={width}:{height}\" -c:v {video_encoder} -preset medium -b:v {bitrate} -pix_fmt yuv420p -threads {threads} -map 0:v:0 -map 0:a:0? -c:a aac -b:a 128k -movflags +faststart \"{output}.{ext}\"",
  "gpu_command": "ffmpeg -y -hide_banner -hwaccel {hwaccel} -i \"{input}\" -vf \"scale={width}:{height}\" -c:v {video_encoder} {gpu_opts} -b:v {bitrate} -pix_fmt yuv420p -map 0:v:0 -map 0:a:0? -c:a aac -b:a 128k -movflags +faststart \"{output}.{ext}\""
}
```

**方式 B：再配一个 `modes/<平台>/mode_<通道>.py`** —— 需要特殊参数逻辑时才写。
里面暴露 `MODE = 你的模式实例`（继承 `BaseMode`）。同 `id` 的 json 会覆盖它的字段。

### 占位符表

| 占位符 | 含义 |
|---|---|
| `{input}` | 主视频完整路径 |
| `{aux}` | 辅视频完整路径（`needs_aux` 为真时才有） |
| `{output}` | 产物路径**不含扩展名** |
| `{ext}` | 扩展名（来自 json 的 `ext`） |
| `{width}` `{height}` `{size}` | 目标分辨率 |
| `{fps}` | 目标帧率 |
| `{threads}` | 线程数 |
| `{bitrate}` | 码率 |
| `{video_encoder}` | CPU 时 `libx264`；GPU 时 `h264_nvenc`/`h264_amf` |
| `{hwaccel}` | GPU 时的硬解方式，默认 `auto` |
| `{gpu_opts}` | **按厂商注入的编码器参数**，见下 |
| `{suffix}` `{mix_seconds}` `{pip_scale}` `{margin}` | 模式自有字段 |

> **`{gpu_opts}` 是必须的，别在 `gpu_command` 里写死编码器参数。**
> NVENC（`-preset p5 -rc vbr -cq 21 …`）和 AMF（`-quality balanced -rc cqp …`）的参数体系
> 完全不兼容，一份模板要同时服务 N 卡和 A 卡，只能靠这个占位符按厂商注入。
> 要改画质就在这里改：`modes/base_mode.py` 的 `_GPU_OPTS`。

> **路径引号写在模板里**（`"{input}"`），因为 `build_params` 给的是不带引号的裸路径。
> 这是与原版的刻意差异：原版在 `build_params` 里就 quote 好了，导致 `{output}.{ext}`
> 的后缀落到引号外面（`"路径".mp4`），输出目录带空格就会被拆开。

---

## 四、产物完整性保障

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
