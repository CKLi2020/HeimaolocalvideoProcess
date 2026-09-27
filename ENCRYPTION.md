# 月落@苍狼：核心保护与正式打包说明

本文说明核心算法是怎样保护的，以及每次发布时应该怎样打包。正式发布只需要按“正式打包步骤”操作。

## 一、保护方案

整体流程如下：

```text
核心算法 flowcut_core.pyx
        ↓ Cython 编译
_flowcut_core.raw.pyd
        ↓ VMProtect Ultra 虚拟化
app/_flowcut_core.pyd
        ↓ Nuitka standalone 打包
月落@苍狼_V版本.exe + 运行依赖
        ↓ 手工使用 SProtect
最终发布 EXE
```

### 1. 原生核心

核心源码位于：

```text
native_src/flowcut_core.pyx
```

当前放入原生核心的内容：

| VMProtect 标记 | 保护内容 |
|---|---|
| `FCALGO:mask.alpha` | 蒙版 Alpha 和羽化表达式 |
| `FCALGO:butterfly.plan` | 蝴蝶 AB 分段计划 |
| `FCALGO:template.window` | 模板中央窗口计算 |
| `FCALGO:concat.segment` | 素材拼接滤镜参数 |

`scripts/build_native.ps1` 会完成以下工作：

1. 用 Cython 把 `.pyx` 转为 C；
2. 用 64 位 MinGW GCC 编译成 `.pyd`；
3. 用 VMProtect Ultimate 对上述四个标记区域进行 Ultra 虚拟化；
4. 导入保护后的 `.pyd` 并调用四组算法做冒烟测试；
5. 测试通过后复制到 `app/_flowcut_core.pyd`。

只要编译、VMProtect 或冒烟测试中任意一步失败，正式打包就会停止。

### 2. 调试版与发布版的区别

源码运行时可以使用 `engine/dev_core.py` 中的等价算法，方便开发和测试。

正式 Nuitka 构建使用：

```text
--nofollow-import-to=engine.dev_core
```

因此调试算法不会被放进发布目录。发布版如果找不到正确版本的 `_flowcut_core.pyd`，会直接报错，不会退回 Python 明文算法。

### 3. 外层程序

Nuitka 使用 standalone 模式生成完整程序目录。这里不再给外层 EXE 套 VMProtect，因为最终外层由 SProtect 处理，避免重复加壳造成启动或兼容问题。

## 二、打包前准备

正式打包前确认电脑已经安装：

- Python 3.9；
- Cython、Nuitka、PySide6；
- VMProtect Ultimate，并包含 SDK；
- FFmpeg 和 FFprobe；
- SProtect。

Python 依赖缺失时运行：

```bat
%LocalAppData%\Programs\Python\Python39\python.exe -m pip install Cython Nuitka PySide6
```

项目默认使用：

```text
C:\Program Files (x86)\VMProtect Ultimate
```

GCC 优先从系统 PATH 查找；没有配置 PATH 时，脚本会自动查找 Nuitka 下载的 64 位 GCC。

## 三、正式打包步骤

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
