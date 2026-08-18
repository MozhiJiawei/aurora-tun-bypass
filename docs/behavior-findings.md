# Aurora Slim 真实行为记录

本文只记录在真实 Aurora Slim 环境中重复实验得到的行为。后续修改持久化方案前，必须先读本文；不要重复采用已经证伪的文件层方案。

## 当前结论

测试环境：Windows、Aurora Slim `5.2.4`，观测日期 `2026-08-15`。

| 结论 | 状态 | 证据 |
| --- | --- | --- |
| `C:\Users\<user>\.aurora-slim\.<hash>` 是加密的生成配置，不是可靠的持久化源。 | 已证实 | 外部补丁可通过摘要和加密 round-trip 校验，但 Aurora 后续启动核心时会重建该文件。 |
| `POST http://127.0.0.1:18090/api/stopsb` 与 `startsb` 只停止/启动同一 `Aurora.exe` 进程内的代理核心，不更换 `Aurora.exe` PID。 | 已证实 | 多轮实验中 GUI PID 与核心宿主 PID 均保持不变。 |
| 核心停止后直接补丁，至少 10 秒内不会被 GUI 单独写回。 | 已证实 | `stopsb` 后写入，10 秒后 dry-run 报告目标进程仍全部存在。 |
| 调用 `startsb` 会从 Aurora 内部状态重新生成配置，并在同一进程内加载默认规则。 | 已证实 | `startsb` 请求约 3 秒返回；返回时磁盘文件已恢复默认，`/rules` 中目标进程全部缺失。 |
| 使用 Windows 文件句柄禁止写入和替换，不能迫使 `startsb` 读取外部候选配置。 | 已证实 | 锁定候选文件时 `startsb` 仍返回 HTTP 200，但 `/rules` 未出现任何目标进程；解锁后恢复启动正常。 |
| `PUT /configs?force=true` 返回 HTTP 204 不代表路由规则已更新。 | 已证实 | 提交包含目标进程的完整候选 JSON 后，`GET /rules` 始终没有目标进程。 |
| 只读文件属性不能阻止覆盖。 | 已证实 | Aurora 使用替换文件的方式绕过只读属性，目标规则随后消失。 |
| 持续 watcher 执行“停止核心→补丁文件→启动核心”不是可接受的持久化方案。 | 已证实/弃用 | `startsb` 本身会重建默认配置，且 watcher 会造成约 1–2 分钟一次的重复核心重载。 |

## 权威验证面

- Aurora 控制 API：`http://127.0.0.1:18090/api`
- Clash 兼容 API：`http://127.0.0.1:19090`
- 判断当前内存是否真正生效时，以 `GET http://127.0.0.1:19090/rules` 为准；只检查磁盘文件不足以证明生效。
- 已观察到的默认直连进程规则只包含常见下载器。梦幻西游目标进程为 `my.exe`、`my_new.exe`、`mhtab.exe`、`mhmain.exe`、`mhrender.exe`、`xyqsvc.exe`。

## 已观测启动时间线

```text
stopsb
  -> 外部写入经验证的候选配置
  -> 核心停止期间候选配置保持不变（已验证 10 秒）
  -> startsb
  -> Aurora 内部 GetSBConfig/SetConfig 链路重建生成配置
  -> 同一 Aurora.exe 进程内启动/热加载代理核心
  -> /rules 只包含 Aurora 内部状态生成的默认规则
```

一次高精度实验中，外部写入发生于 `09:46:19.201`，`09:46:29.508` 仍存在；`startsb` 于 `09:48:58.373` 调用，约 `09:49:01.397` 返回时活动规则已经恢复默认。

## 对注入方案的约束

文件层持久化已经证伪。下一步只优先研究以下注入点：

1. Aurora 内部 `aurora-client/service/settings.GetSBConfig` 返回值；
2. `aurora-client/common/singbox.(*Box).SetConfig` 的入参；
3. `startsb` 生成配置之后、代理核心解析配置之前的同进程内存数据；
4. 如果存在未发现的受支持本地 API，必须用 `/rules` 验证，而不能只看 HTTP 状态码。

任何方案都必须证明：目标进程出现在活动 `/rules`，并能承受 Aurora 的下一次内部刷新。不能再把“磁盘候选文件包含目标进程”当作完成标准。

## 已定位的内存调用链

`Aurora.exe` 是保留 Go `gopclntab` 的 64 位 PE。当前 `5.2.4` 样本的 PE ImageBase 为 `0x400000`，关键静态虚拟地址如下；升级后必须重新解析符号，不能硬编码跨版本复用。

| Go 符号 | 静态虚拟地址 | 已确认行为 |
| --- | --- | --- |
| `aurora-client/service/settings.APIStartSB` | `0x120c2c0` | 调用 `GetSBConfig`，成功后把返回切片传给 `Box.SetConfig`。 |
| `aurora-client/service/settings.GetSBConfig` | `0x120cc00` | 从 Aurora 内部数据库和状态生成 sing-box 配置字节。 |
| `aurora-client/common/singbox.(*Box).SetConfig` | `0x11cb080` | 接收 `[]byte`，把 data/len/cap 保存到 `Box +0x30/+0x38/+0x40`。 |
| `aurora-client/common/singbox.(*Box).readConfig` | `0x11cbd40` | 从上述字段读取字节并调用 sing-box `Options.UnmarshalJSON`。 |

在 Windows amd64 Go 内部 ABI 下，`SetConfig` 入口已观察到：`RAX` 为 `*Box`，`RBX/RCX/RDI` 分别为配置 `[]byte` 的 data/len/cap。因而最小注入方向是在每次 `SetConfig` 调用时修改该切片，而不是修改生成文件。动态地址应按 `实际模块基址 + (静态地址 - 0x400000)` 计算。

## 已验证的内存注入

状态：`2026-08-15` 已在真实运行核心验证成功。

只读 hook 捕获到 `SetConfig` 入参是完整 sing-box JSON，原始长度 `17569` 字节，顶层键为 `dns`、`experimental`、`inbounds`、`limiters`、`log`、`outbounds`、`route`。默认下载器直连规则位于当次配置的 `route.rules[3]`；实现时不得依赖固定索引，应按 `outbound == direct` 且存在 `process_name` 数组定位。

在 `SetConfig` 入口复制 JSON、向现有直连 `process_name` 追加 6 个目标进程，并把 `RBX/RCX/RDI` 改为新切片后：

- 修改后长度为 `17644` 字节；
- Aurora 原有解析和启动流程继续完成；
- 活动 `/rules` 中 `my.exe`、`my_new.exe`、`mhtab.exe`、`mhmain.exe`、`mhrender.exe`、`xyqsvc.exe` 全部存在；
- 同一启动链路第二次调用 `SetConfig` 时，hook 检测到目标已存在，没有重复追加。

这证明 `SetConfig` 是当前版本可用的内存注入点。持久化实现必须让 hook 在 Aurora 进程生命周期内保持附加，才能覆盖后续内部刷新；只注入一次后立即卸载 hook 仍不足以承受未来刷新。

## 持久化维护器验证

`2026-08-15` 已把维护器安装到 `%LOCALAPPDATA%\AuroraTunBypass`，并注册 HKCU Run 值 `AuroraTunBypass`。维护器行为如下：

- 登录后等待 `Aurora.exe`；发现新 PID 后附加；
- 从当前可执行文件的 Go `gopclntab` 动态解析 `Box.SetConfig` RVA；
- 活动规则已存在时不重载核心；首次附加且规则缺失时只执行一次 `stopsb/startsb`；
- 在 Aurora 进程生命周期内保持 hook，每次 `SetConfig` 都合并目标进程；
- 使用命名 mutex 防止同一用户会话重复运行；
- 只把脱敏事件写入 `status.json` 和轮转日志，不记录完整配置。

安装后的强制刷新测试明确观察到 `injected`，紧接着同链路第二次调用为 `already_present`；刷新完成后活动 `/rules` 仍为 6/6 命中，维护器仍存活，`status.json` 为 `active_rules_verified` 且 `ok: true`。这是当前持久化方案的最低回归测试。

## 跨登录与新进程验收

`2026-08-15` 用户执行电脑重启操作后再次检查：

- HKCU Run 值 `AuroraTunBypass` 仍存在；
- 新维护器进程 PID 为 `7680`，创建时间 `14:37:58`；
- 新 Aurora GUI PID 为 `35772`，核心 PID 为 `28248`，启动时间分别为 `15:20:15` 和 `15:20:18`；
- 维护器于 `15:20:25` 写入 `active_rules_verified`，`ok: true`；
- 活动 `/rules` 中 6 个目标进程全部存在。

这次实验证实 HKCU 登录启动、新 Aurora PID 发现、动态符号解析、自动附加和首次规则注入均能跨用户会话工作。Windows `LastBootUpTime` 仍显示 `2026-08-14 17:59:26`，说明本次很可能经过 Windows 快速启动/混合关机，而不是完整冷启动；因此当前证据应表述为“跨登录和进程重启已验证”，不要误写为“已完成冷启动内核验收”。

## 后续回归验收

`2026-08-17 11:15` 再次检查通过：维护器仅 1 个实例（PID `26432`），Aurora 核心为新 PID `20768`，活动 `/rules` API 正常，6 个目标进程全部仍为 `true`。这说明维护器在连续运行两天及 Aurora 新进程启动后仍保持有效。

同日新增微信直连目标时，实际进程识别为 `Weixin.exe` 和 `WeChatAppEx.exe`；dry-run 校验通过后更新维护器目标列表。`11:26:16` 验证结果为 8/8 命中（原 6 个梦幻进程加微信 2 个进程），维护器 PID 为 `45628`，仍只有一个实例。

## 维护器可靠性复查

`2026-08-18` 根据静态审查修正了维护器生命周期和验证逻辑：

- 旧文件 watcher 的安装与运行入口已删除，避免它与内存维护器共享启动项后并存、反复重载核心；
- 重复执行 `install-memory-hook` 默认合并已有目标，先停止旧维护器，再原子替换脚本和设置，并等待新 PID 报告活动规则验证成功；
- 新维护器使用 `stop.request` 和 `injector.pid` 支持立即退出；升级旧版本时，仅对命令行明确指向安装目录脚本的残留进程执行兜底终止；
- `/rules` 验证不再做原始文本子串搜索，只解析 JSON 中 `proxy=direct` 规则的 `process_name=[...]`，并按大小写不敏感的完整文件名匹配；
- 文件诊断补丁和内存 hook 都要求配置中恰好存在一条 `direct + process_name` 规则；遇到零条或多条即停止，避免修改语义不确定的规则。

这些是实现层修正；是否在真实 Aurora 环境生效，仍必须按上文标准完成安装、活动 `/rules` 和强制 stop/start 三项验证后才能标记为已验收。

同日完成真实环境验收：新版维护器先从旧实现迁移到 PID `37048`，安装命令返回 `active_rules_verified: true`；强制 `stopsb/startsb` 后日志连续出现 `injected` 和 `already_present`，精确解析活动 `/rules` 仍为 8/8 命中，且只有一个维护器实例。随后仅用 `--process Weixin.exe` 再次安装，旧维护器通过停止握手退出，新维护器 PID 为 `39560`；结果仍保留原有 8 个目标并验证成功，证明默认合并和运行中升级路径已生效。

## 实验产物

本轮原始时间线、加密快照和候选配置位于 `.tmp/aurora-tun-bypass/refresh-analysis/`。它们包含本机敏感配置，只能留在本地临时目录，禁止提交。
