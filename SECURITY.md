# FlowCut 授权与程序保护

- 应用 ID：`blackcat-flowcut`
- 授权接口：`https://yizhixiangsi.cn/api/license/{activate,check}`
- 请求：HTTPS + HMAC-SHA256 + 时间戳 + nonce
- 响应：FlowCut 独立 Ed25519 公钥验签 + HMAC 校验
- 设备绑定：Windows MachineGuid 的 SHA-256 指纹
- 本地卡密：`%APPDATA%\BlackCatFlowCut\license.json`
- 每个处理批次申请最长 5 分钟的 Ed25519 签名任务令牌

服务器必须配置：

```text
BLACKCAT_FLOWCUT_PRIVATE_KEY=<.flowcut_private_key.pem 的 PEM 内容>
BLACKCAT_FLOWCUT_REQUEST_SECRET=fc-client-request-v1-8c7f67c5e4fa49c3888e21135d72976a
```

发布时运行 `build_protected.bat`。脚本使用 Nuitka onefile 编译，再以
VMProtect Ultra 保护入口点，输出到 `dist-protected\黑猫苍老师.exe`。

构建会先生成 `app\_flowcut_core.pyd`，以下逻辑没有 Python 回退：

- 授权请求 HMAC 签名
- Ed25519 服务器响应验签
- 蒙版 Alpha/羽化表达式
- 签名任务令牌及完整作用域校验
- 令牌授权后的蒙版 Alpha/羽化表达式
- 令牌授权后的蝴蝶 AB 隐藏段、分块和关键帧计划

六段逻辑分别使用 VMProtect Ultra 标记虚拟化；原生模块保护失败时，
最终 EXE 构建会直接终止。

任务令牌绑定应用、通道、批次、输入数量、完整参数哈希、设备码、
设备指纹和过期时间。蒙版导出和蝴蝶 AB 处理计划在原生核心中再次
验签；缺少令牌、字段被替换、签名被修改或令牌过期都会拒绝处理。
Python 处理线程只传递令牌和作用域，不使用授权布尔值放行。

成品视频保持标准 MP4，不使用参考项目的 `BCVIDEO1` 私有加密容器。
