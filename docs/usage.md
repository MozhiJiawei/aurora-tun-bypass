# 使用方式

## 典型 Prompt

- `请用 aurora-tun-bypass 把梦幻西游排除在 Aurora 的 TUN 全局代理外，但保留 ChatGPT 走代理；先识别真实进程名，再备份并修改规则。`
- `请只检查 Aurora 当前的 TUN 进程直连规则，不要修改配置。`
- `请把上次 aurora-tun-bypass 生成的备份恢复回去；由我负责退出和重启 Aurora。`

## 推荐流程

1. 确认用户授权修改 Aurora 本地配置。
2. 从 Windows 实际进程识别主程序、启动器和可能的子进程。
3. 检查依赖并运行脱敏 inspect。
4. 先 dry-run，核对目标配置键和新增进程名。
5. 阅读 `docs/behavior-findings.md`；不要把文件补丁或旧 watcher 当作持久化方案。
6. 通过 `install-memory-hook` 安装 `SetConfig` 内存注入维护器。
7. 核对 `%LOCALAPPDATA%\AuroraTunBypass\status.json` 的 `active_rules_verified/ok: true`，并直接检查 `GET 127.0.0.1:19090/rules`。
8. 主动执行一次核心 stop/start，确认日志出现 `injected`，刷新后目标规则仍在。

## 命令

以下命令均从 workspace 根目录运行。

检查依赖：

```powershell
python skills/aurora-tun-bypass/verify_dependencies.py
```

脱敏检查：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py inspect
```

为梦幻西游生成 dry-run 候选配置：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py patch `
  --process my.exe `
  --process my_new.exe `
  --output-dir .tmp/aurora-tun-bypass/mhxy
```

文件层重载探针（只用于诊断，当前版本会被 `startsb` 重建）：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py patch `
  --process my.exe `
  --process my_new.exe `
  --output-dir .tmp/aurora-tun-bypass/mhxy `
  --reload-core --apply
```

安装一次、以后在每次 `SetConfig` 内存刷新时自动合并：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py install-memory-hook `
  --process my.exe `
  --process my_new.exe
```

用户明确要求移除时，停止维护器、删除启动入口，并重载核心清除内存规则：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py uninstall-memory-hook
```

恢复备份：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py restore `
  --backup .tmp/aurora-tun-bypass/mhxy/backups/aurora-config-<timestamp>.enc `
  --apply
```

测试脚本时使用配置副本：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py `
  --config .tmp/aurora-tun-bypass/test/config-copy.enc `
  patch --process sample-game.exe `
  --output-dir .tmp/aurora-tun-bypass/test/output `
  --apply
```

## 输入与输出

| 项目 | 说明 |
| --- | --- |
| 输入 | Aurora 加密配置、一个或多个可执行文件 basename、目标 TUN 配置键。 |
| 输出 | 脱敏 JSON 结果、诊断候选与备份；持久化模式安装 `%LOCALAPPDATA%\AuroraTunBypass` 内存维护器和用户级启动项。 |
| 临时目录 | workspace 根目录下的 `.tmp/aurora-tun-bypass/<task>/`。 |

## 完成标准

- dry-run 返回 `digest_ok: true` 和 `round_trip_ok: true`，仅用于确认格式与规则形状。
- 内存维护器状态为 `active_rules_verified` 且 `ok: true`。
- 活动 `/rules` 包含所有目标进程，而磁盘文件可以仍是 Aurora 默认生成内容。
- 一次强制 stop/start 后日志出现 `injected`，活动规则仍为全部目标命中。
- ChatGPT 等未匹配流量继续命中原有代理兜底。

默认不需要子 Agent 或 checker；不要让独立测试触碰实时配置。
