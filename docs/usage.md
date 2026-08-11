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
5. 让用户完全退出 Aurora，包括托盘进程。
6. 使用 `--apply` 写入，核对备份和摘要校验结果。
7. 让用户重启、连接并测试目标程序及一个仍需代理的应用。

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

用户退出 Aurora 后执行写入：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py patch `
  --process my.exe `
  --process my_new.exe `
  --output-dir .tmp/aurora-tun-bypass/mhxy `
  --apply
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
| 输出 | 脱敏 JSON 结果、`patched-config.enc`、时间戳备份。 |
| 临时目录 | workspace 根目录下的 `.tmp/aurora-tun-bypass/<task>/`。 |

## 完成标准

- dry-run 与 apply 均返回 `digest_ok: true` 和 `round_trip_ok: true`。
- `changes` 只包含预期配置键和进程名，或在重复执行时显示 `already_present: true`。
- apply 返回可读取的备份路径；restore 返回恢复前快照路径。
- 用户重启 Aurora 后，目标程序可用，ChatGPT 等未匹配流量仍能通过全局代理。

默认不需要子 Agent 或 checker；不要让独立测试触碰实时配置。
