# 月落@苍狼：核心保护与正式打包说明

本文说明核心算法是怎样保护的，以及每次发布时应该怎样打包。正式发布只需要按“正式打包步骤”操作。

## 一、保护方案

整体流程如下：

```text
核心算法 flowcut_core.pyx                核心算法 random_frame_swap_core.pyx
        ↓ Cython 编译                            ↓ Cython 编译
_flowcut_core.raw.pyd                    _random_frame_swap_core.raw.pyd
        ↓ VMProtect Ultra 虚拟化                 ↓ VMProtect Ultra 虚拟化
app/_flowcut_core.pyd                    app/_random_frame_swap_core.pyd
        ↓ Nuitka standalone 打包（两颗核心一起收进 app/）
月落@苍狼_V版本.exe + 运行依赖
        ↓ 手工使用 SProtect
最终发布 EXE
```

### 1. 原生核心

核心源码位于：

```text
native_src/flowcut_core.pyx            主算法（17 个 FCALGO 标记）
native_src/random_frame_swap_core.pyx  爆闪帧序交换（3 个 RFCORE 标记）
```

当前放入原生核心的内容：

| VMProtect 标记 | 保护内容 |
|---|---|
| `FCALGO:mask.alpha` | 蒙版 Alpha 和羽化表达式 |
| `FCALGO:butterfly.plan` | 蝴蝶 AB 分段计划 |
| `FCALGO:template.window` | 模板中央窗口计算 |
| `FCALGO:concat.segment` | 素材拼接滤镜参数 |
| `FCALGO:random.playback` | 随机播放速率 |
| `FCALGO:random.filter` | 随机滤镜分段 |
| `FCALGO:color.adjust` | 调色参数 |
| `FCALGO:audio.mild` | 人声柔化滤镜 |
| `FCALGO:qilin.1004.pipeline` | 云麒 1004 合成管线 |
| `FCALGO:liuying.1003.*` | 流影 1003 的五段（video / branch / flash / base / seed） |
| `RFCORE:graph` | 爆闪拼接滤镜图 |
| `RFCORE:shuffle` | 帧序洗牌 |
| `RFCORE:offsets` | ctts 时间戳偏移重算 |

主核心当前包含 17 个 `FCALGO:*` 标记，覆盖云麒 SPS 兼容与两条星轮管线；爆闪核心另有 3 个 `RFCORE:*` 标记。宿主门禁本身不增加 VMProtect 区域。

`scripts/build_native.ps1` 对两颗核心各完成以下工作：

1. 用 Cython 把 `.pyx` 转为 C；
2. 用 64 位 MinGW GCC 编译成 `.pyd`（发布构建额外定义 `FC_LICENSE_GATE`，
   打开宿主机门禁，详见 SECURITY.md）；
3. 用 VMProtect Ultimate 虚拟化该核心的标记区域；
4. 按 `engine/native_core.py` 声明的导出清单（`_REQUIRED` / `RANDOM_SWAP_REQUIRED`）
   校验保护后的 `.pyd` 导出齐全；
5. 未启用宿主门禁时，导入保护后的 `.pyd` 并调用算法做冒烟测试；
6. 复制到 `app/`，启用门禁的构建在 Nuitka 打包完成后由正式 EXE 自检两颗核心。

只要编译、VMProtect、导出校验或冒烟测试中任意一步失败，正式打包就会停止。

`scripts/build_protected.ps1` 默认使用两个编译任务以降低构建峰值内存，可用 `-Jobs`
调整。验证构建可以用 `-OutputRoot` 指定独立输出根目录，避免覆盖已有客户包；
未指定时仍输出到项目的 `build/protected` 和 `dist-protected`。
构建开始前检查必需的 `resources`，缺失则明确报错。
`贴纸` 和 `配置文件` 是可选素材目录：存在时完整复制，缺失时打印警告并在发布包中
创建空目录，程序使用内置默认配置或用户选择的素材，不阻断打包。
该资源检查与 FCG1 宿主门禁误判不同。

宿主门禁的共同实现位于 `native_src/host_gate.h`。比较的是 Windows 目录的卷标识和文件标识，
不是路径字符串：Nuitka 可能用中文目录的 8.3 短路径加载 `.pyd`，这与 EXE 的长路径
实际是同一个目录；目录链接也按其实际目标判断。门禁仍然启用，不允许不同发布目录混用。

正式 EXE 支持 `--native-core-self-test`，不打开界面、不修改用户配置，调用全部核心算法，
并验证后台线程调用。结果保存在发布目录的 `native-core-self-test.json`。
构建脚本会自动运行该检查，失败或超时不会报告构建成功。移动发布目录或加 SProtect 后，
也应重新运行此检查。正常启动时先检查宿主门禁，失败会显示原因并写入
`logs/native_core_error.log`，不再等到点击处理才无提示消失。

星河摩轮、天穹星澜的媒体探测和公共 FFmpeg 分阶段执行器均使用 `CREATE_NO_WINDOW`，
避免 GUI 版处理时黑色控制台一闪而过；日志、进度和退出码仍按原方式处理。

### 2. 调试版与发布版的区别

源码运行时可以使用 `engine/dev_core.py` 中的等价算法，方便开发和测试。

正式 Nuitka 构建使用：

```text
--nofollow-import-to=engine.dev_core
```

因此调试算法不会被放进发布目录。发布版如果找不到正确版本的 `_flowcut_core.pyd`，会直接报错，不会退回 Python 明文算法。

### 2.1 通道配方也必须编译进产物

除核心算法外，各通道自己的 ffmpeg 配方（滤镜图、编码参数）同样属于要保密的内容。

**硬规则：通道配方只能是编译进 `modes` 包的 Python 模块常量，不得用
`--include-data-files` 送进发布包。** 后者等于把配方明文交给任何解压发布包的人。

以飞猫／听雪为例，它的配方放在：

```text
modes/douyin/feimao_recipe.py      FILTER_GRAPH（滤镜图）+ FFARGS（编码参数）
```

由 `--include-package=modes` 自动编译进启动器。原先的 `modes/douyin/filter_complex.txt`
与 `modes/douyin/feimao_ffargs.json` 两个数据文件已删除，**不要**把它们加回
`build_protected.ps1`：`build_release_manifest.py` 与 `verify_release.py` 都把它们列为
禁止项，一旦重新出现在发布包就会中止构建或自检失败。

例外只有 `modes/douyin/feimao_metadata.txt`：ffmpeg 必须从真实路径读它，且它的
`title` 会写进成品 MP4，所以保持文件形态。

### 3. 外层程序

Nuitka 使用 standalone 模式生成完整程序目录。这里不再给外层 EXE 套 VMProtect，因为最终外层由 SProtect 处理，避免重复加壳造成启动或兼容问题。

## 二、打包前准备

正式打包前确认电脑已经安装：

- 项目虚拟环境 `.venv`（先运行 `安装.bat` 创建；构建使用其 Python 解释器）；
- Cython、Nuitka、PySide6；
- VMProtect Ultimate，并包含 SDK；
- FFmpeg 和 FFprobe；
- SProtect。

Python 依赖缺失时运行：

```bat
.venv\Scripts\python.exe -m pip install Cython Nuitka PySide6
```

`build_protected.bat` 固定使用项目的 `.venv\Scripts\python.exe`，无需手动激活虚拟环境。原生核构建根据该解释器的版本选择对应的 Python 链接库，并从基础 Python 安装目录读取头文件和库文件，不再依赖固定的 Python 3.9 安装路径。

项目默认使用：

```text
C:\Program Files (x86)\VMProtect Ultimate
```

GCC 优先从系统 PATH 查找，并用 `-dumpmachine` 验证必须是 x86_64 MinGW。
32 位 GCC 会被明确忽略，然后查找 Nuitka 缓存及 `C:\msys64` 的 64 位工具链；
也可以向 `scripts/build_native.ps1` 传入 `-Gcc` 指定编译器。原生构建要求 64 位 Python，
不能只设置 `MS_WIN64` 宏却使用 32 位编译器。

## 三、正式打包步骤

### 排查加密后闪退：仅 Nuitka 的独立测试版

运行根目录 `build_nuitka_debug.bat`。它使用 `.venv`，仅用 Nuitka
生成 standalone EXE，不执行 VMProtect/SProtect，不加载两颗加密原生核心，
而由独立入口 `main_nuitka_debug.py` 显式使用开发等价核心。正式加密入口和
发布版禁止开发核心回退的规则保持不变。

产物位于 `dist-nuitka-debug\<名称>_V<版本>_<时间戳>\`，不会覆盖正式发布目录。
请保留整个目录，不能只复制 EXE。双击产物目录中的 `run_nuitka_debug.bat`
运行；软件退出后 BAT 会显示控制台日志和退出码并暂停。
`logs\console_*.log` 保存输出及退出码，`logs\diagnostic_*.log`
保存 Python 异常和 faulthandler 崩溃信息。

可向 EXE 或启动 BAT 传入 `--diagnostic-smoke-test`，检查开发核心、
全部平台通道加载和 Qt 窗口初始化后自动退出。该测试版不用于正式发布；
它用于对照排查保护层是否导致闪退，并不能单凭正常启动证明闪退原因。

### 第 1 步：关闭正在运行的软件

先关闭“月落@苍狼”和从本项目启动的 Python 窗口。

Windows 在程序运行时会锁定 `_flowcut_core.pyd`。如果没有关闭，构建时会提示：

```text
Cannot replace ... _flowcut_core.pyd
```

### 第 2 步：确认名称和版本

打开根目录的 `version.py`：

```python
APP_NAME = "月落@苍狼"
APP_VERSION = "1.2.0"
```

准备发布新版本时只修改 `APP_VERSION`。版本格式使用三段或四段数字，例如 `1.2.1`。

### 第 3 步：生成核心已保护的 standalone 包

双击运行：

```text
build_protected.bat
```

也可以在项目根目录的命令行运行：

```bat
build_protected.bat
```

脚本会自动完成：

1. 编译原生核心；
2. 用 VMProtect Ultra 保护核心；
3. 测试保护后的核心；
4. 使用 Nuitka 生成 standalone 程序；
5. 复制 FFmpeg、资源文件和工作目录。

成功后生成：

```text
dist-protected\月落@苍狼_V1.2.0\
```

里面的外层启动器是：

```text
月落@苍狼_V1.2.0.exe
```

此时原生核心已经保护，但外层 EXE 还没有经过 SProtect。

### 第 4 步：使用 SProtect 保护外层 EXE

在 SProtect 中选择发布目录里的启动器：

```text
dist-protected\月落@苍狼_V1.2.0\月落@苍狼_V1.2.0.exe
```

不要选择 `build` 目录里的中间文件，也不要单独处理 `_flowcut_core.pyd`；核心 `.pyd` 已经由 VMProtect 处理完成。

按照现有 SProtect 配置执行保护，并把输出放回同一个发布目录，名称必须是：

```text
月落@苍狼_V1.2.0.sp.exe
```

如果 SProtect 自动生成了其他名称，手动改成上面的 `.sp.exe` 名称。

### 第 5 步：完成发布包

回到项目根目录，双击运行：

```text
finalize_sprotect_release.bat
```

收尾脚本会：

1. 检查原 EXE 和 `.sp.exe` 是否都存在；
2. 检查两个文件大小是否合理；
3. 检查两个文件的 SHA-256 是否不同；
4. 把未加 SProtect 的原 EXE 备份到：

   ```text
   build\protected\sprotect-backups\
   ```

5. 把 `.sp.exe` 替换为正式文件名；
6. 在发布目录生成 `SHA256SUMS.txt`。

完成后，正式启动器仍叫：

```text
月落@苍狼_V1.2.0.exe
```

但它已经是 SProtect 处理后的文件。

### 第 6 步：发布前测试

不要只测试 EXE 文件，要测试整个发布目录。至少检查：

1. 软件可以正常启动；
2. 蒙版通道可以生成视频；
3. 蝴蝶 AB 通道可以生成视频；
4. 模板和辅助视频切换正常；
5. 素材拼接的头部、尾部和同时拼接都正常；
6. FFmpeg 和 FFprobe 没有缺失；
7. 换到一台没有开发环境的电脑上也能运行。

测试无误后，把整个目录压缩发送：

```text
dist-protected\月落@苍狼_V1.2.0\
```

不能只发送 EXE，因为 standalone 模式依赖同目录中的 DLL、插件和资源。

## 四、发布目录检查

正式发布目录中应该包含：

- SProtect 处理后的主 EXE；
- Nuitka 运行库、PySide6 插件和 DLL；
- `ffmpeg.exe`、`ffprobe.exe`；
- `resources`、`ico`、`showlight`、`startmovie` 等资源；
- 主视频、辅助视频、模板、成品等工作目录；
- `SHA256SUMS.txt`。

正式发布目录中不应该包含：

- `.sp.exe` 临时文件；
- `.unprotected.exe` 未保护启动器；
- Python 源码；
- `engine/dev_core.py`；
- VMProtect 或 SProtect 工程文件；
- 测试视频和历史成品。

## 五、常见错误

### `_flowcut_core.pyd` 正在使用

关闭“月落@苍狼”和相关 Python 进程，再重新运行 `build_protected.bat`。

### 找不到 VMProtect

确认下面文件存在：

```text
C:\Program Files (x86)\VMProtect Ultimate\VMProtect_Con.exe
```

### 找不到 GCC

先运行一次 Nuitka 构建，让 Nuitka 下载 GCC；或者把 64 位 MinGW 的 `bin` 目录加入 PATH。

### 收尾脚本提示找不到 `.sp.exe`

确认 SProtect 输出位于当前版本的发布目录，并严格命名为：

```text
月落@苍狼_V当前版本.sp.exe
```

### 收尾脚本提示备份已经存在

说明同一版本可能已经完成过收尾。检查：

```text
build\protected\sprotect-backups\
```

确认情况后再决定是提高版本号重新构建，还是手工保存并移走旧备份。

## 六、安全边界

这套方案提高算法提取、静态分析和篡改的成本，但不能保证客户端程序绝对不可破解。没有服务器密钥体系时，把 AES 密钥直接放在客户端没有实际保密意义，因此当前方案采用“原生编译 + VMProtect 核心虚拟化 + Nuitka + SProtect 外层保护”，没有增加虚假的本地 AES 加密层。
