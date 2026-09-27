# 月落@苍狼 V1.2.0 抗逆向评估

评估对象：`dist-protected/月落@苍狼_V1.2.0`

评估方式：只读静态检查。没有修改发布包、绕过保护或执行破坏性测试。

## 总体结论

当前版本对普通用户和简单反编译工具有较好的阻挡作用，但面对熟悉 Windows、Python/Cython 和动态调试的逆向人员，整体属于**中等难度**，不能评价为“很难破解”。

| 项目 | 评价 |
|---|---|
| 防止直接看到 Python 源码 | 较好 |
| 原生核心静态反编译难度 | 较好 |
| 外层 EXE 静态分析难度 | 中上 |
| 动态调用与黑盒复现防护 | 较弱 |
| 文件完整性与替换防护 | 较弱 |
| 发布可信度与防篡改证明 | 较弱 |
| 综合抗逆向能力 | 中等，约 5～6/10 |

## 已确认有效的保护

### 1. SProtect 外层已经生效

`月落@苍狼_V1.2.0.sp.exe` 的入口点位于自定义代码段 `.zqjsq` 中，该段约 47.5 MB，整个文件熵约 7.903。常规 `.text`、`.data`、`.rdata` 的原始内容已被隐藏或迁移，说明外层不是简单改名，确实进行了打包或代码变换。

没有从外层 EXE 中直接搜索到以下核心名称：

- `mask_alpha`
- `butterfly_plan`
- `window_matte_chain`
- `concat_filter_segment`
- `engine.dev_core`

### 2. VMProtect 原生核心已经生效

`app/_flowcut_core.pyd` 包含约 4 MB 的 `.vmp0` 代码段，整个文件熵约 7.545。PE 函数表已经被保护转换，公开导出只剩：

```text
PyInit__flowcut_core
```

没有公开导出四个核心算法的原生地址，也没有保留普通符号表。

### 3. 没有明显开发文件泄漏

发布目录中没有发现：

- `.py`、`.pyc`；
- PDB、MAP；
- C/C++ 中间源码；
- `engine/dev_core.py`；
- VMProtect 工程文件；
- 名称带 `raw`、`debug` 或 `unprotected` 的发布文件。

## 主要薄弱点

### HIGH：核心行为仍然可以被黑盒观察

四个核心函数是 Python 扩展模块的可调用接口。虽然函数内部被 VMProtect 虚拟化，但运行程序时仍然必须接收普通参数并返回普通字符串或字典。

这意味着有经验的分析者不一定需要恢复 VMProtect 内部指令，可以观察多组输入和输出，再复现公式。当前四个函数以确定性的 FFmpeg 参数和分段计算为主，行为复杂度不高，因此“代码反编译很难”不等于“算法无法复制”。

建议：把更完整的处理决策、参数组合和关键校验一起放入原生核心，减少简单的一问一答式函数边界。真正需要保密的规则应由服务器参与，不能只依赖客户端壳。

### HIGH：原生核心没有与主程序进行可信绑定

发布版会检查 `_flowcut_core.pyd` 是否存在以及接口是否完整，但没有使用签名清单验证它是不是官方构建的文件。发布目录中的 `.pyd` 是独立旁加载文件，攻击者可以研究替换整个模块，而不必先拆开 SProtect 外层。

当前 `SHA256SUMS.txt` 只是普通哈希文本，本身可以和文件一起被修改，不能作为防篡改信任根。

建议：构建时使用私钥签署发布清单；主程序中只保存公钥，启动时验证 `_flowcut_core.pyd` 和关键 DLL 的哈希与清单签名。签名失败立即退出。

### MEDIUM：仍然容易识别为 Python/Nuitka 程序

外层 EXE 的导入表仍显示 `python39.dll`，发布目录也包含 `python39.dll`、PySide6 和大量 Python 扩展模块。分析者可以快速判断技术栈，并选择针对 Python C API、Nuitka 和运行时内存的分析方法。

SProtect 提高了静态分析成本，但不能阻止程序运行后在内存中恢复必要代码和数据。

### MEDIUM：程序和核心均未进行 Authenticode 签名

检查结果：

```text
月落@苍狼_V1.2.0.sp.exe  NotSigned
app/_flowcut_core.pyd     NotSigned
```

未签名不会直接让算法更容易反编译，但会带来以下问题：

- 用户无法验证文件是否来自官方；
- 被第三方替换后没有系统级签名告警；
- 高熵加壳程序更容易触发 SmartScreen 或杀毒软件警告。

建议：SProtect 完成后再对最终 EXE 和关键 `.pyd` 做 Authenticode 签名并加时间戳。签名必须是发布流程的最后步骤之一。

### LOW：核心仍残留少量元数据

`_flowcut_core.pyd` 中仍能看到：

- `flowcut_core.pyx`；
- `native_src`；
- 四个 Python 层函数名称；
- 内部 DLL 名 `_flowcut_core.raw.pyd`。

这些内容不会直接泄露算法，但能帮助分析者快速定位目标。

建议：GCC 链接时启用完整符号剥离，并使用 `-ffile-prefix-map` 清除源码路径；在不影响调用的情况下减少模块文档和错误消息。

## 当前发布状态

当前目录只有：

```text
月落@苍狼_V1.2.0.sp.exe
```

并且仍有 `SPROTECT-NEXT-STEP.txt`，说明尚未执行正式收尾。发布前应运行：

```text
finalize_sprotect_release.bat
```

生成正式文件名和 `SHA256SUMS.txt` 后，再做完整启动与视频处理测试。

## 建议的加固顺序

1. **先做签名清单和运行时完整性验证**，绑定主程序、核心 `.pyd` 和关键 DLL。
2. **把更完整的业务决策移入原生核心**，减少可枚举的简单算法接口。
3. **对最终 EXE 和核心做 Authenticode 签名**，签名放在 SProtect 之后。
4. 清理 Cython 源文件名、路径和内部 raw 文件名等元数据。
5. 如果算法商业价值很高，引入服务器签名的短期任务参数；不要把长期秘密密钥放在客户端。

## 文件指纹

```text
SProtect EXE SHA-256:
4CE3C64E5272AAA2CE262BF37ED8B1DA3AFC0C76BE6A11568D272712686E37C7

VMProtect core SHA-256:
72B9A710E91F356D2D27BFC12A0EEE19B21B903338C4BE5E08928065D6BF6709
```
