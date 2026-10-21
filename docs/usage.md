# 使用方式

## 典型 Prompt

- `请只检查 Aurora 当前的 TUN 进程直连规则，不要修改配置、安装维护器或重载核心。`
- `请用 aurora-tun-bypass 为梦幻西游生成 dry-run 候选配置，先识别真实进程名，不要写入真实配置。`
- `请用 aurora-tun-bypass 让梦幻西游在 Aurora TUN 下持续直连，保留其他流量现有代理兜底；授权安装用户级内存维护器和登录启动项，先 dry-run，再验证一次核心刷新后的规则。`
- `请把上次 aurora-tun-bypass 生成的备份恢复回去；由我负责完全退出和重新启动 Aurora。`

## 输入、输出与工作目录

以下命令均从 workspace 根目录运行。把 `<run-id>` 替换为本次工作已创建的 run 标识，所有步骤共用它。默认工作根为 `.tmp/runs/<run-id>/aurora-tun-bypass/`；仅当用户明确指定长期工作目录时才改用对应 retained 路径。

| 项目 | 说明 |
| --- | --- |
| 输入 | Aurora 加密配置或副本、一个或多个可执行文件 basename；默认配置键是 `global_tun_config` 和 `tun_config`。 |
| 只读输出 | stdout 中的摘要校验与路由概况；包含本机路径和进程名，公开前需脱敏。 |
| dry-run 输出 | `patched-config.enc`，以及 stdout 中的 `changes`、`digest_ok`、`round_trip_ok` 和路由概况；不会生成备份或覆盖输入。 |
| 文件写入输出 | 显式 `--apply` 才写入并生成 `backups/aurora-config-<timestamp>.enc`；恢复前另外生成 `pre-restore-<timestamp>.enc`。 |
| 持久化输出 | `%LOCALAPPDATA%\AuroraTunBypass` 下的脚本、Frida 运行库、`settings.json`、`status.json`、日志，以及 HKCU Run 启动项。该目录是授权安装产物，不能替代本次临时工作目录。 |

真实配置、候选、备份及未脱敏日志只留在本机，不上传或提交。公开示例见[合成配置 dry-run 报告](examples/synthetic-dry-run.html)。

## 只读检查与候选生成

先运行依赖自检；它的检查范围与按任务判断方式见[依赖说明](dependencies.md)。

```powershell
python skills/aurora-tun-bypass/verify_dependencies.py
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py inspect
```

从 Windows 实际进程识别主程序、启动器和子进程；不要仅凭窗口标题推测。可在目标应用运行后用 `Get-CimInstance Win32_Process` 检查相关进程，只保留需要的 executable basename。

生成 dry-run 候选：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py patch `
  --process my.exe --process my_new.exe `
  --output-dir .tmp/runs/<run-id>/aurora-tun-bypass/mhxy
```

测试时必须显式指定已准备好的副本；`--config`、`--config-key` 属于全局参数，放在子命令之前：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py `
  --config .tmp/runs/<run-id>/aurora-tun-bypass/copy/config-copy.enc `
  patch --process sample-game.exe `
  --output-dir .tmp/runs/<run-id>/aurora-tun-bypass/copy/output
```

文件补丁与内存 hook 都只接受恰好一条既有 `outbound=direct` 且 `process_name` 为数组的规则。遇到零条或多条时停止调查，不自动创建或任意选择规则。

## 安装持久化维护器

只读检查与候选生成不授权真实配置写入、内存注入或登录启动项。只有用户明确要求持久化并授权这些变更后，才执行本节；开始前阅读<a href="/skill-static/aurora-tun-bypass/behavior-findings.md" target="_blank" rel="noopener noreferrer">真实行为记录</a>（工作区原文件为 `skills/aurora-tun-bypass/docs/behavior-findings.md`）。

若 Frida 尚未安装，可先放入本次临时目录，再仅在当前命令过程中加入 `PYTHONPATH`。安装命令会将它复制到维护器目录：

```powershell
$fridaDeps = Join-Path (Get-Location) '.tmp/runs/<run-id>/aurora-tun-bypass/deps'
python -m pip install --target "$fridaDeps" frida
$savedPythonPath = $env:PYTHONPATH
try {
  $env:PYTHONPATH = if ($savedPythonPath) { "$fridaDeps;$savedPythonPath" } else { $fridaDeps }
  python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py install-memory-hook `
    --process my.exe --process my_new.exe
} finally {
  $env:PYTHONPATH = $savedPythonPath
}
```

Frida 已可导入时，可直接运行上述 `install-memory-hook` 命令。重复安装默认合并原有目标并替换旧维护器；只有明确要替换完整目标列表时才使用 `--replace-processes`。首次附加且目标活动规则缺失时会短暂 stop/start 核心，GUI 保持运行。

## 核对安装与活动规则

安装成功输出必须包含 `active_rules_verified: true`。还应核对启动项、恰好一个维护器实例和状态文件：

```powershell
Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name AuroraTunBypass
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*\AuroraTunBypass\aurora_memory_injector.pyw*' } | Select-Object ProcessId
Get-Content -Raw "$env:LOCALAPPDATA\AuroraTunBypass\status.json" | ConvertFrom-Json | Select-Object event,ok,injector_pid,matches
```

下例复用脚本的精确匹配函数，直接验证活动 `/rules`；将目标列表换成实际授权名单。输出必须逐项为 `true`：

```powershell
@'
import json, sys, urllib.request
sys.path.insert(0, 'skills/aurora-tun-bypass/scripts')
from aurora_rules import active_matches
with urllib.request.urlopen('http://127.0.0.1:19090/rules', timeout=3) as response:
    matches = active_matches(response.read().decode('utf-8'), ['my.exe', 'my_new.exe'])
print(json.dumps(matches, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(matches.values()) else 1)
'@ | python -
```

在授权的持久化验收中，再强制刷新一次核心，然后重新运行上面的活动规则检查，并检查 `injector.log` 中本次刷新对应的 `injected` 或 `already_present` 事件：

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:18090/api/stopsb'
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:18090/api/startsb'
Get-Content -Tail 20 "$env:LOCALAPPDATA\AuroraTunBypass\injector.log"
```

`status.json` 是最近一次状态事件，初次附加后的 `active_rules_verified` 不代表持续探测成功。每次刷新后的结论须来自当次活动 `/rules`；同时核对原有兜底和应用流量。脚本保留未修改规则，不会自动证明 ChatGPT 等应用实际走了哪条链路。

## 文件诊断与恢复

只有另行授权真实文件诊断时，才使用 `--reload-core --apply`。Aurora Slim `5.2.4` 已记录 `startsb` 重建配置的行为，脚本会因规则被重写而报错并尝试回滚；不能把候选生成或磁盘写入当作持久化成功：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py patch `
  --process my.exe --process my_new.exe `
  --output-dir .tmp/runs/<run-id>/aurora-tun-bypass/diagnostic `
  --reload-core --apply
```

恢复前由用户完全退出 Aurora，确认目标备份属于这次安装，再执行：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py restore `
  --backup .tmp/runs/<run-id>/aurora-tun-bypass/mhxy/backups/aurora-config-<timestamp>.enc `
  --apply
```

恢复只恢复磁盘内容，不会卸载内存维护器；如需取消持续直连，必须另行卸载。用户明确要求移除维护器时运行：

```powershell
python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py uninstall-memory-hook
```

默认卸载会停止维护器、删除启动入口，并在 Aurora 运行时刷新核心；随后仍须核对进程和启动项已消失，以及活动规则已恢复预期。安装目录不会因此自动删除。未运行核心或 API 不可用时，输出字段不能替代人工复核。

## 完成标准

- 只读检查：摘要有效，报告所选配置键与路由形状，不写入真实配置。
- dry-run：返回 `digest_ok: true`、`round_trip_ok: true`，核对新增进程与既有规则；它只证明文件处理，不证明运行生效。
- 文件诊断/恢复：写前备份、写后校验通过；明确报告磁盘结果与运行效果的区别。
- 持久化：HKCU Run 存在、维护器恰好一个、`active_rules_verified/ok: true`，当次活动 `/rules` 对全部目标精确命中；一次强制刷新后再次通过，并验证原有代理兜底和相关应用效果。
- 卸载：启动项和维护器已消失，核心刷新后活动规则符合预期；不以返回的状态字符串单独判定成功。

默认不需要子 Agent 或 checker；若上层任务另行委派 reviewer，只交接脱敏输出，不让其接触真实配置或进行实时 forward-test。
