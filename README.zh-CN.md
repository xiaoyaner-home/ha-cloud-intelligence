# 云智能 Home Assistant 本地集成

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

**Beta 本地集成。** 独立、非官方社区项目，首款仅支持
Wilo HiMulti-1 WiFi。它导入用户自己从 Android 云智能取得的单设备局域网授权，
不是账号登录或云端设备发现；不实现 Google 登录、授权提取或自动续期，也不假设 App 有导出菜单。

## 功能与安装

- 原生 Wilo 设备，12 个只读状态：水压、水温、目标压力、模式、故障代码、故障、
  开机许可、电机运行、启动压力比例、软件版本、目标/实际转速。无运行控制实体或服务。
- 每台设备一个标准 HA 配置条目，可添加多台；授权持久化、重启恢复、重新导入及修改地址。
- 默认 120 秒本地轮询，最短 60 秒。每轮总预算 10 秒，收齐 12 个实际状态立即结束。
  不依赖常开 App、云连接、私有脚本或常驻监听。
- 验证环境为 HA 2026.9.1 / Python 3.14.6。离线生命周期测试使用合成通信；
  另已在真实设备上验证首次配置、12 个原生状态、自动轮询和完整 HA 进程重启。
  重启后原配置条目及全部设备/实体 ID 保持不变，无需重导授权即可读到新状态。
- 短期观察中有一次定时读取失败，下一周期自动恢复。长期无人值守、浏览器视觉验收和其它型号
  仍待进一步验证。

将代码中的整个 `custom_components/cloud_intelligence` 文件夹（含 `_core`、
`translations`）复制至 HA 配置目录的 `custom_components` 下并重启。然后在
**设置 → 设备与服务 → 添加集成 → Cloud Intelligence (Local)** 中导入：

| 字段 | 内容 |
| --- | --- |
| Name | 显示名称，默认 Wilo HiMulti-1 WiFi |
| Host | HA 可访问的设备局域网私有 IPv4 地址，不接受公网 IP 或域名 |
| `productKey` | 仅支持 `a15zaTr5sp1` |
| `deviceName` | 授权内的固定 ALCS 设备身份，不是昵称 |
| `accessKey`、`accessToken` | 您本人设备的本地授权，均属敏感信息 |

不需要 `iotId` 或云账号密码。HA 必须能与该设备 UDP 5683 双向通信，不做组播扫描。
添加时必须验证设备身份、授权和 12 个完整状态，ACK 或刷新回显不算成功。
每轮仅发送一次固定 `refresh=1` **遥测回报请求**，不改开机、模式或压力；因此不是纯 GET 或被动监听。
未知型号拒绝主动回报请求，TSL 可写标记不启用控制。

### HACS 安装

在 HACS 的 **自定义存储库** 中添加
`https://github.com/xiaoyaner0201/ha-cloud-intelligence`，类型选 **Integration**，下载后重启 HA，
再到「设备与服务」添加 **Cloud Intelligence (Local)**。目前通过自定义仓提供 Beta，未收录进默认商店。

也可从 [GitHub Releases](https://github.com/xiaoyaner0201/ha-cloud-intelligence/releases) 下载手动安装 ZIP。
ZIP 已含 `custom_components/cloud_intelligence/...` 路径，解压到 HA 配置目录后应存在
`custom_components/cloud_intelligence/manifest.json`。HACS 使用仓库源文件安装，不消费这个手动 ZIP。
不要复制仓库根目录的 `cloud_intelligence` 包。

## 稳定端点候选（尚未实机验证）

同一客户端首次由 OS 分配认证/Observe UDP 源端口，此后成功、失败、超时或取消后均重新绑定该端口。
每轮仍用独立临时 socket 精确校验设备身份，再认证、订阅、发送一次固定回报请求，并关闭全部 socket。
同一客户端并发读取立即失败、不排队；获准读取仍共享每轮 10 秒总预算。端口冲突明确失败，不偷偷换端口或
增加重试。不新增端口配置、共享 socket、复用选项、常驻监听或心跳。轮次之间不保留端口占用，端口不进入
配置、诊断或 repr；新客户端或新进程可以选择新端口。

此 Beta 变更仅减少端点变动，以便单变量长稳比较；上文既有实机记录不代表本候选已通过实机验证。
本地关闭不等于远端会话/观察者 teardown，同端点重新认证也不保证清理或恢复。未假定 Observe=1/RST 清理，
不宣称修复硬件故障根因。发布前仍需独立审查和受限实机长稳验收。

## 保密、恢复和限制

授权保存于 HA 标准配置条目，**本集成不加密**。请保护配置目录、备份及 HA 访问权限，
不要在 Issue、截图或日志中暴露凭据、设备身份、地址或原始报文。保存不延长有效期。
授权失效时按 HA 重新认证提示重新导入同一 `productKey` + `deviceName` 的授权；不同设备会被拒绝。
地址变化可用条目的 **重新配置** 操作，同时重新填写授权；轮询间隔位于选项。

离线启动使用 HA 标准重试，轮询失败实体不可用；后续局部报文缺失的字段显示未知，不补零或沿用旧值。
开机许可和电机运行分开。局域网可达不代表云在线；`locally_received_at` 是 HA 本机实际接收时间，
不是设备源时间戳。支持的 ALCS opt 1 没有逐包 MAC 或防重放保护，仅用于可信局域网。

长期运行、固件差异、凭据失效和浏览器视觉效果仍需进一步验证。完整账号发现、Google 登录、自动续期、
其它型号和运行控制不在本候选范围。基础 UI 含英文、简体、繁体、日语及英文回退，不宣称全语言完成。

开发环境先安装 [固定工具](requirements-dev.txt)，`make check` 包含纯 Python 核心检查及断网、
2 GiB/2 CPU 的真实 HA 2026.9.1 容器测试；`make check-core` 和 `make check-ha` 可分别运行。
详见 [英文完整说明](README.md)、[需求](docs/requirements.md)、[验证](docs/verification.md) 与
[安全政策](SECURITY.md)。许可证 [Apache-2.0](LICENSE)。
