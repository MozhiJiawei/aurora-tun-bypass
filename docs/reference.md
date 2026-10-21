# 能力展示

这个 Skill 把 Aurora TUN 的“指定应用不走代理”需求转成可预览的文件候选与经授权的常驻内存规则维护；文件诊断另有备份与恢复路径。

## 可打开的公开交付示例

[打开合成配置 dry-run 报告](examples/synthetic-dry-run.html)，查看两种嵌套配置形态的真实脚本输出摘要、规则前后变化及验证边界。配套的[公开输入](/skill-static/aurora-tun-bypass/examples/synthetic-input.json)与[脱敏结果 JSON](/skill-static/aurora-tun-bypass/examples/synthetic-dry-run-result.json)均不含真实账户、节点、用户名或本机路径。

这个示例于 `2026-10-16` 使用手工构造的最小规则输入，通过本 Skill 的 `encrypt_config` 生成测试文件，再显式传入 `--config` 执行 `inspect` 与不带 `--apply` 的 `patch`。两个配置键分别采用 JSON 字符串与对象，真实返回 `status: dry_run`、`digest_ok: true`、`round_trip_ok: true`，追加 4 个“配置键:进程名”条目；源文件未变、未生成备份，原有 `Proxy` 兜底保持不变。报告是文件处理示范，不是 Aurora 在线状态或持久化验收报告。

## 已验证案例

| 场景 | 识别到的进程 | 规则变化 | 结果 |
| --- | --- | --- | --- |
| 梦幻西游绕过 Aurora 全局 TUN | `my.exe`、`my_new.exe`、`mhtab.exe`、`mhmain.exe`、`mhrender.exe`、`xyqsvc.exe` | 在每次 `Box.SetConfig` 内存入参中追加到现有直连规则 | 强制核心刷新后活动 `/rules` 仍为 6/6 命中，其他未匹配流量保留原代理兜底。 |
| 微信绕过 Aurora 全局 TUN | `Weixin.exe`、`WeChatAppEx.exe` | 同一内存 hook 追加到现有直连规则 | 更新维护器目标列表后活动 `/rules` 8/8 命中。 |

上述历史案例来自 Windows Aurora Slim `5.2.4` 的本地排障记录，具体观测日期与证据边界见<a href="/skill-static/aurora-tun-bypass/behavior-findings.md" target="_blank" rel="noopener noreferrer">真实行为记录</a>。公开材料只保留进程名、规则形状和记录中的结果；原始敏感日志不公开，因此这些历史数值并非本轮重新执行的验收结果。用户配置、账号、订阅、节点与备份均不进入仓库。

## 能力点

- 自动定位当前 Windows 用户的 Aurora Slim 配置文件。
- 在解密前后验证配置内置的 SHA-256 摘要。
- 只展示 TUN 路由数量、进程规则和最后一条规则的摘要，不输出其他顶层配置；本机路径与进程名仍须在公开前脱敏。
- 在全局与智能 TUN 配置中追加一个或多个进程名。
- 保留嵌套配置原有的 JSON 字符串或对象形态。
- 在写入前生成时间戳备份；写后复验失败时自动回滚；restore 前另存恢复前快照。
- 处理 Windows 隐藏文件属性，写入后恢复原属性。
- 动态解析 Go `gopclntab` 定位当前版本 `Box.SetConfig`，不硬编码 ASLR 后地址。
- 在 `SetConfig` 入口合并内存 JSON；Aurora 每次内部刷新都会经过同一个 hook。
- 可安装用户级登录启动维护器；重复安装默认合并目标并替换旧实例。卸载请求停止维护器、删除启动项，默认在 Aurora 运行时重载核心；须复核实际进程与规则结果。
- 活动验证解析 `/rules` JSON，只接受 `direct` 规则中的完整进程名，不使用文本子串猜测。

## 交付件

`patch` 会在显式指定的 `.tmp/runs/<run-id>/aurora-tun-bypass/<task>/` 生成候选，只有 `--apply` 才生成备份：

```text
patched-config.enc
backups/                       # 仅 apply
`-- aurora-config-<timestamp>.enc
```

这些是本机敏感产物，只用于当前任务和恢复，不提供真实文件在线链接，也不得上传到 GitHub。上方公开 HTML/JSON 用独立合成输入展示交付结构，不包含这些本机产物。

## 能力边界

- 当前只验证过 Aurora Slim `5.2.4`；升级后必须先 inspect。
- 规则基于 Windows 进程 basename，不按域名、IP 或完整路径匹配。
- Skill 不保证目标程序只使用一个进程，必须先观察真实运行进程。
- Skill 不停止或重启 Aurora GUI；首次附加若活动规则缺失，会短暂重载一次代理核心。
- Aurora 升级后必须重新解析并验证 Go 符号与调用约定；找不到符号时本次附加失败并记录错误，维护器会等待重试，不猜地址。
- 脚本只保留原有非目标规则，不校验兜底一定名为 `Proxy`，也不自动证明其他应用的实际流量仍走代理。
- 维护器状态与日志是事件记录；持续生效须以每次关键刷新后的活动 `/rules` 和应用效果验收。
