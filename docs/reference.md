# 能力展示

这个 Skill 把 Aurora TUN 的“指定应用不走代理”需求转成可预览、可备份、可恢复的本地配置变更。

## 已验证案例

| 场景 | 识别到的进程 | 规则变化 | 结果 |
| --- | --- | --- | --- |
| 梦幻西游绕过 Aurora 全局 TUN | `my.exe`、`my_new.exe`、`mhtab.exe`、`mhmain.exe`、`mhrender.exe`、`xyqsvc.exe` | 在每次 `Box.SetConfig` 内存入参中追加到现有直连规则 | 强制核心刷新后活动 `/rules` 仍为 6/6 命中，其他未匹配流量保留原代理兜底。 |
| 微信绕过 Aurora 全局 TUN | `Weixin.exe`、`WeChatAppEx.exe` | 同一内存 hook 追加到现有直连规则 | 更新维护器目标列表后活动 `/rules` 8/8 命中。 |

示例来源是 Windows Aurora Slim `5.2.4` 的真实本地排障，公开材料只保留脱敏后的进程名、规则形状和验证结果；用户配置、账号、订阅、节点与备份均不进入仓库。

## 能力点

- 自动定位当前 Windows 用户的 Aurora Slim 配置文件。
- 在解密前后验证配置内置的 SHA-256 摘要。
- 只展示 TUN 路由数量、进程规则和最终兜底，不泄露其他配置。
- 在全局与智能 TUN 配置中追加一个或多个进程名。
- 保留嵌套配置原有的 JSON 字符串或对象形态。
- 在写入前生成时间戳备份；写后复验失败时自动回滚；restore 前另存恢复前快照。
- 处理 Windows 隐藏文件属性，写入后恢复原属性。
- 动态解析 Go `gopclntab` 定位当前版本 `Box.SetConfig`，不硬编码 ASLR 后地址。
- 在 `SetConfig` 入口合并内存 JSON；Aurora 每次内部刷新都会经过同一个 hook。
- 可安装用户级登录启动维护器；重复安装默认合并目标并可靠替换旧实例，卸载会立即停止维护器并重载核心清除注入结果。
- 活动验证解析 `/rules` JSON，只接受 `direct` 规则中的完整进程名，不使用文本子串猜测。

## 交付件

脚本调用会在 `.tmp/aurora-tun-bypass/<task>/` 生成：

```text
patched-config.enc
backups/
`-- aurora-config-<timestamp>.enc
```

这些是本机敏感产物，只用于当前任务和恢复，不提供在线链接，也不得上传到 GitHub。可公开复用的交付件是本 Skill 的脚本、格式参考和执行规范。

## 能力边界

- 当前只验证过 Aurora Slim `5.2.4`；升级后必须先 inspect。
- 规则基于 Windows 进程 basename，不按域名、IP 或完整路径匹配。
- Skill 不保证目标程序只使用一个进程，必须先观察真实运行进程。
- Skill 不停止或重启 Aurora GUI；首次附加若活动规则缺失，会短暂重载一次代理核心。
- Aurora 升级后必须重新解析并验证 Go 符号与调用约定；找不到符号时维护器停止注入，不猜地址。
