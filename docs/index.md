# Aurora TUN 进程绕过

`aurora-tun-bypass` 在不改变 Aurora 全局代理兜底规则的前提下，把指定 Windows 可执行文件加入现有 `direct` 规则。它适合“ChatGPT 必须继续走 TUN 全局代理，但某个游戏或本地应用必须直连”的场景。

## 逻辑视图

| 模块 | 输入与职责 | 输出与边界 |
| --- | --- | --- |
| 进程识别 | 用户场景与 Windows 进程列表 | 只产生可执行文件 basename；不按窗口标题猜测。 |
| 格式层 | Aurora 加密配置 | 校验摘要并解析顶层 JSON；不展示账号、节点等无关字段。 |
| 路由补丁层 | 目标进程名、TUN 配置键 | 只追加到现有 `direct/process_name` 规则，保留 `Proxy` 兜底。 |
| 安全写入层 | 已验证的候选配置 | 先备份，处理 Windows 隐藏属性，写入后再次解密比对。 |
| 核心重载层 | Aurora 本地回环 API | 停止代理核心、写入、重新启动并做稳定性复检；不结束 GUI。 |
| 行为分析层 | 磁盘时间线、本地 API 与活动 `/rules` | 区分生成配置、内部状态和实际内存规则，排除无效持久化方案。 |
| 恢复层 | 时间戳备份 | 先保存恢复前快照，再校验并原样恢复，不合并其他内容。 |

主要输入是进程名和 Aurora 本地配置；输出是脱敏检查结果、候选加密配置、时间戳备份与写入结果。真实配置和备份必须留在 workspace 的 `.tmp/aurora-tun-bypass/`，不得进入子仓。

## 运行视图

```text
用户提出绕过需求
  -> 主 Agent 确认授权并识别真实进程名
  -> verify_dependencies.py 检查 Windows、cryptography 与配置文件
  -> inspect 脱敏检查摘要和路由形状
  -> patch dry-run 生成候选配置并 round-trip 校验
  -> patch dry-run 验证文件格式与候选规则
  -> 读取 behavior-findings.md，避开已证伪的文件层持久化
  -> install-memory-hook 动态定位 SetConfig 并保持内存 hook
  -> 以内存 /rules 验证目标进程
  -> 强制 stop/start 刷新后再次验证
  -> [异常] 退出 Aurora 后用 restore 保存当前快照并恢复备份
```

默认保持 Aurora GUI 运行。`--reload-core` 只用于行为诊断；旧文件 watcher 已移除，跨刷新持久化统一使用 `install-memory-hook`。开始相关工作前必须阅读 [真实行为记录](behavior-findings.md)。

## 开发视图

| 文件 | 职责 |
| --- | --- |
| `SKILL.md` | Agent 的执行顺序、安全边界与完成标准。 |
| `scripts/aurora_tun_bypass.py` | inspect、patch、restore，以及内存维护器的安装、升级与卸载。 |
| `scripts/aurora_memory_injector.py` | 动态定位 `SetConfig`、维护 hook 并验证活动规则。 |
| `scripts/aurora_rules.py` | 精确解析活动 `/rules` 中的直连进程名。 |
| `references/aurora-format.md` | 版本敏感的文件格式、路由结构与重新调查方法。 |
| `docs/behavior-findings.md` | 真实环境中已证实、已排除和待验证的 Aurora 行为。 |
| `verify_dependencies.py` | 检查外部运行前置条件。 |
| `docs/` | 文档站发布所需的能力、用法、依赖与架构页面。 |

## 多 Agent 职责边界

本 Skill 默认由一个主 Agent 完成，不要求子 Agent 或 checker。

| 角色 | 职责 | 禁止事项 |
| --- | --- | --- |
| 主 Agent | 确认修改授权、识别进程、调用脚本、核对结果与恢复。 | 不输出完整解密配置，不把备份提交到 Git，不结束 Aurora GUI。 |
| 用户 | 授权配置修改并验证应用效果。 | 不应在核心重载期间切换 Aurora 模式或退出客户端。 |
| 脚本 | 校验与备份文件、动态解析 Go 符号、安装内存 hook、验证活动规则和恢复。 | 不结束 GUI，不修改未知路由结构，不访问 Aurora 账号服务。 |
| 可选 reviewer | 只在上层任务另有要求时审查脱敏输出或代码。 | 不接触真实配置和备份，不对实时 Aurora 安装执行 forward-test。 |
