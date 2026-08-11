# Aurora TUN 进程绕过

`aurora-tun-bypass` 在不改变 Aurora 全局代理兜底规则的前提下，把指定 Windows 可执行文件加入现有 `direct` 规则。它适合“ChatGPT 必须继续走 TUN 全局代理，但某个游戏或本地应用必须直连”的场景。

## 逻辑视图

| 模块 | 输入与职责 | 输出与边界 |
| --- | --- | --- |
| 进程识别 | 用户场景与 Windows 进程列表 | 只产生可执行文件 basename；不按窗口标题猜测。 |
| 格式层 | Aurora 加密配置 | 校验摘要并解析顶层 JSON；不展示账号、节点等无关字段。 |
| 路由补丁层 | 目标进程名、TUN 配置键 | 只追加到现有 `direct/process_name` 规则，保留 `Proxy` 兜底。 |
| 安全写入层 | 已验证的候选配置 | 先备份，处理 Windows 隐藏属性，写入后再次解密比对。 |
| 恢复层 | 时间戳备份 | 先保存恢复前快照，再校验并原样恢复，不合并其他内容。 |

主要输入是进程名和 Aurora 本地配置；输出是脱敏检查结果、候选加密配置、时间戳备份与写入结果。真实配置和备份必须留在 workspace 的 `.tmp/aurora-tun-bypass/`，不得进入子仓。

## 运行视图

```text
用户提出绕过需求
  -> 主 Agent 确认授权并识别真实进程名
  -> verify_dependencies.py 检查 Windows、cryptography 与配置文件
  -> inspect 脱敏检查摘要和路由形状
  -> patch dry-run 生成候选配置并 round-trip 校验
  -> 用户完全退出 Aurora
  -> patch --apply 先备份、再替换、最后复验
  -> 用户重启 Aurora 并验证目标程序与其他代理流量
  -> [异常] 退出 Aurora 后用 restore 保存当前快照并恢复备份
```

默认拒绝在 Aurora 运行时修改真实配置，避免客户端退出或切换模式时覆盖补丁。`--allow-running` 只用于用户明确接受这一风险的特殊情况。

## 开发视图

| 文件 | 职责 |
| --- | --- |
| `SKILL.md` | Agent 的执行顺序、安全边界与完成标准。 |
| `scripts/aurora_tun_bypass.py` | inspect、patch、restore 与加密摘要校验。 |
| `references/aurora-format.md` | 版本敏感的文件格式、路由结构与重新调查方法。 |
| `verify_dependencies.py` | 检查外部运行前置条件。 |
| `docs/` | 文档站发布所需的能力、用法、依赖与架构页面。 |

## 多 Agent 职责边界

本 Skill 默认由一个主 Agent 完成，不要求子 Agent 或 checker。

| 角色 | 职责 | 禁止事项 |
| --- | --- | --- |
| 主 Agent | 确认修改授权、识别进程、调用脚本、核对结果、指导重启与恢复。 | 不输出完整解密配置，不把备份提交到 Git，不擅自停止用户程序。 |
| 用户 | 授权配置修改、按提示退出和重启 Aurora、验证应用效果。 | 不应在写入过程中切换 Aurora 模式或退出客户端。 |
| 脚本 | 完成确定性的校验、补丁、备份、写入和恢复。 | 不主动结束进程，不修改未知路由结构，不访问 Aurora 账号服务。 |
| 可选 reviewer | 只在上层任务另有要求时审查脱敏输出或代码。 | 不接触真实配置和备份，不对实时 Aurora 安装执行 forward-test。 |
