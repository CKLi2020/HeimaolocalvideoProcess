# 黑猫苍老师：构建、加壳与授权保护流程

## 1. 当前结论

默认运行 `build_protected.bat` 构建时，成品会经过以下保护：

1. 关键授权与处理逻辑由 Cython 编译为原生 `.pyd`。
2. 原生核心中的关键函数使用 VMProtect Ultra 虚拟化保护。
3. Python 主程序使用 Nuitka 编译为 Windows onefile EXE。
4. 最终 EXE 的入口点再次使用 VMProtect 保护。
5. 每次批量处理前必须向服务器申请短期 Ed25519 签名任务令牌。

这套方案是“原生编译 + VMProtect 加壳/虚拟化 + 服务器签名授权”，不能理解为源码和运行数据绝对不可逆的整体加密。

## 2. 唯一版本配置

版本号在项目根目录的 `version.py` 中配置：

```python
APP_VERSION = "1.0.0"
```

构建脚本会将该版本同步用于：

- 登录窗口和主窗口标题；
- 客户端授权请求中的 `appVersion`；
- Windows EXE 的文件版本和产品版本；
- 成品文件名，例如 `黑猫苍老师_V1.0.0.exe`。

## 3. 默认构建入口

发布时运行：

```bat
build_protected.bat
```

该批处理会调用：

```powershell
scripts\build_protected.ps1
```

默认构建不会跳过 VMProtect。如果 VMProtect、Cython、GCC、Nuitka 或原生依赖缺失，构建会直接失败，不会静默生成未保护版本。

`scripts\build_protected.ps1` 提供了开发用的 `-SkipVmProtect` 参数。手动使用该参数时，最终 EXE 不会执行最后一层 VMProtect 入口保护，因此不能作为正式发布包。

## 4. 第一层：原生核心编译

`scripts\build_native.ps1` 执行以下流程：

```text
native_src\flowcut_core.pyx
        ↓ Cython
临时 flowcut_core.c
        ↓ GCC 编译
_flowcut_core.raw.pyd
        ↓ VMProtect Ultra
app\_flowcut_core.pyd
```

原生模块生成后会立即执行导入和函数调用测试。测试失败时，整个正式构建终止。

原生核心没有 Python 回退实现。缺少或破坏 `app\_flowcut_core.pyd` 时，授权模块和受保护处理流程无法正常运行。

## 5. 原生核心保护范围

以下关键区域使用 `VMProtectBeginUltra` / `VMProtectEnd` 标记，并由构建脚本配置为 VMProtect Ultra 虚拟化：

| 标记 | 作用 |
|---|---|
| `FCNATIVE:license.sign` | 授权请求 HMAC 签名 |
| `FCNATIVE:license.verify` | Ed25519 服务器响应验签 |
| `FCNATIVE:mask.alpha` | 蒙版 Alpha/羽化表达式计算 |
| `FCNATIVE:task.verify` | 短期任务令牌验签与作用域校验 |
| `FCNATIVE:mask.authorized` | 验证令牌后生成蒙版处理参数 |
| `FCNATIVE:butterfly.authorized` | 验证令牌后生成蝴蝶 AB 隐藏段和关键帧计划 |

其中蒙版通道与蝴蝶 AB 通道的关键处理计划，不依赖 Python 层传入一个简单的 `True/False` 放行值。

## 6. 第二层：Nuitka 主程序编译

原生核心生成后，`scripts\build_protected.ps1` 使用 Nuitka：

- `--standalone --onefile` 编译并封装 Python 主程序；
- 打包 PySide6、Cryptography 和 `app._flowcut_core`；
- 打包图标和运行资源；
- 关闭 Windows 控制台窗口；
- 写入产品名称、描述和版本信息。

Nuitka 会把 Python 程序编译为 C/C++ 级别的可执行程序并封装依赖。onefile 封装和压缩本身不等于密码学加密，但比直接分发 `.py` 或普通 PyInstaller 字节码更难直接还原。

中间产物位于：

```text
build\protected\BlackCatFlowCut.nuitka.exe
```

该文件还不是最终发布文件。

## 7. 第三层：最终 EXE 加壳

Nuitka 构建完成后，脚本自动生成 VMProtect 项目文件，并使用 VMProtect 保护 EXE 入口点：

```text
BlackCatFlowCut.nuitka.exe
        ↓ VMProtect
dist-protected\黑猫苍老师_V<版本号>.exe
```

脚本会检查 VMProtect 返回码和最终文件是否存在。保护失败时构建终止。

当前最终 EXE 层保护的是入口点；关键业务函数的更强虚拟化保护位于前面的原生 `.pyd` 层。

## 8. 运行时服务器授权

应用 ID 为：

```text
blackcat-flowcut
```

客户端授权请求包含：

- 卡密；
- 设备码；
- 设备指纹；
- 时间戳；
- nonce；
- request ID；
- session ID；
- 应用 ID 和版本号；
- HMAC-SHA256 请求签名。

通信只允许 HTTPS；仅开发环境允许访问 `localhost` 或 `127.0.0.1` 的 HTTP 地址。

服务器响应同时包含：

- Ed25519 签名；
- HMAC 校验值；
- 服务器时间和响应 ID；
- 授权状态及授权数据。

客户端在原生核心中验证 Ed25519 签名，并再次校验响应 HMAC。响应字段、签名或校验值被修改时，客户端拒绝授权。

服务器的 Ed25519 私钥只保存在服务器环境中，不进入客户端构建包。客户端只包含公钥。

## 9. 短期任务令牌

软件登录成功不代表可以无限期直接处理。每次启动一个批量处理任务时，客户端会向服务器申请短期签名任务令牌。

任务令牌绑定：

- 应用 ID；
- 处理通道：`flowcut-hdh` 或 `flowcut-ab`；
- 批次 ID；
- 输入数量；
- 完整参数 SHA-256；
- 设备码；
- 设备指纹；
- 签发时间和过期时间。

FlowCut 任务令牌最长有效期为 5 分钟。处理线程收到令牌后，先在原生核心验签；蒙版参数和蝴蝶 AB 处理计划生成时还会再次验证同一令牌和作用域。

以下情况会拒绝处理：

- 没有任务令牌；
- 签名被修改；
- 令牌已过期；
- 通道、批次、输入数量或参数哈希不一致；
- 设备码或设备指纹不一致。

因此，单纯修改 Python 层的授权返回值，不能构造完整且匹配的受保护处理计划。

## 10. 本地数据与成品视频

用户选择记住卡密时，本地配置保存在：

```text
%APPDATA%\BlackCatFlowCut\license.json
```

该文件不是加密保险库，不应在其中保存服务器私钥或其他服务端机密。

输出视频保持标准 MP4，可由普通播放器直接播放。当前项目没有对成品视频使用私有加密容器，这是为了保证平台上传和播放器兼容性。

## 11. 正式发布检查

正式发布前确认：

1. 修改 `version.py` 中的版本号。
2. 使用 `build_protected.bat`，不要传入 `-SkipVmProtect`。
3. 构建日志出现 `Protected native core`。
4. 构建日志出现 `Protected executable`。
5. 只发布 `dist-protected` 中带版本号的最终 EXE。
6. 不发布 `build\protected` 中的 Nuitka 中间 EXE。
7. 不发布 `.flowcut_private_key.pem`、服务器环境配置或数据库备份。
8. 在干净电脑上验证登录、HDH 蒙版、蝴蝶 AB 和任务令牌过期后的拒绝行为。

构建脚本会同时复制 `ico`、`resources`、`showlight`、`startmovie`、`贴纸`
和 `配置文件`，并复制 `ffmpeg.exe`、`ffprobe.exe`。脚本只创建空的
`主视频`、`辅助视频`、`蒙版成品`、`蝴蝶AB成品` 目录，不会复制开发机
中的测试视频或历史成品。包含开发机绝对路径的 `config.json` 也不会进入
发布目录，软件首次启动时会在 EXE 旁生成新的相对路径配置。

## 12. 安全边界

客户端保护只能提高逆向、篡改和绕过成本，无法承诺绝对不可破解。真正不能下发到客户端的机密必须保留在服务器。

当前最重要的服务端信任根是 FlowCut Ed25519 私钥。客户端内的公钥、请求签名逻辑和 VMProtect 保护用于验证服务器与提高篡改成本，但不替代服务器侧卡密校验、任务令牌签发、频率限制、日志和密钥轮换。
