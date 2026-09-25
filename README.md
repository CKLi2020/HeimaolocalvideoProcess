# 月落@苍狼·本地视频处理

本仓库以「月落@苍狼」的 `YanJingwenhua` 分支为唯一基础，在原界面和原有功能上增加了「03 本地视频处理」通道。

## 已整合功能

- 01 蒙版通道
- 02 素材拼接
- 03 本地视频处理：支持主/辅视频文件或文件夹批处理，包含抖音、快手、视频号、小红书、TK、百家、哔哩和多多 8 类模式

## 源码启动

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

```powershell
scripts\finalize_sprotect_release.bat
```
