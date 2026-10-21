# 依赖说明

## 检查命令

在 workspace 根目录运行：

```powershell
python skills/aurora-tun-bypass/verify_dependencies.py
```

脚本返回 JSON；`ok: true` 且退出码为 `0` 表示它列出的检查通过。退出码 `1` 表示至少一项未满足。当前自检统一把 Windows、`cryptography`、`frida` 和真实 Aurora 配置列为 `required`，没有按子命令分组，也没有 `optional` 字段；只做副本 dry-run 时，应结合下表判断失败项是否属于所选任务。

## 按任务区分必需依赖

| 依赖 | 哪些任务必需 | 缺失时的处理 |
| --- | --- | --- |
| Windows 与 Python 3.10+ | 受支持的 Aurora 本机工作流；Python 用于所有脚本。 | 在安装 Aurora 的 Windows 用户会话中运行，使用受支持的 Python 3。 |
| `cryptography` | `inspect`、`patch`、`restore`，以及通过统一 CLI 发起维护器安装/卸载。 | 在所用 Python 环境中运行 `python -m pip install cryptography`，或使用离线 wheel。 |
| Aurora Slim 加密配置或格式兼容的副本 | `inspect`、`patch`、`restore`。 | 真实任务先正常安装并至少运行一次 Aurora；副本测试用全局 `--config` 显式传入副本路径。 |
| `frida` | 内存维护器安装和运行；文件检查、候选生成与恢复不使用它。 | 安装到本次 `.tmp/runs/<run-id>/aurora-tun-bypass/deps/`，把该目录放到当前进程的 `PYTHONPATH` 后再调用安装命令，见[使用方式](usage.md#安装持久化维护器)。 |
| 正在运行的兼容版 `Aurora.exe`、可附加权限 | 内存 hook 与活动规则验收。 | 在同一 Windows 用户会话中启动 Aurora；附加失败时检查版本和进程权限，不回退到旧文件 watcher。 |
| Aurora 控制 API `127.0.0.1:18090/api` | 文件重载诊断；维护器首次附加且目标规则缺失时的核心刷新；默认卸载刷新。 | 确认 Aurora GUI 正常运行，回环 API 可用。 |
| 活动规则 API `127.0.0.1:19090/rules` | 内存维护器验收与刷新后复验。 | 确认代理核心运行；HTTP 成功仍需解析 JSON 并匹配 `direct` 中的完整进程名。 |
| HKCU Run 与 `%LOCALAPPDATA%\AuroraTunBypass` 写权限 | 用户级维护器安装、升级、卸载。 | 当前用户须能写自己的启动项和安装目录；只读诊断不需要这些写权限。 |

安装会把 Frida 复制到 `%LOCALAPPDATA%\AuroraTunBypass\lib`，启动项引用安装时所用 Python 路径。因此不要删除或移动该 Python 环境，否则登录自启动会失效。脚本不需要 Aurora 账号密码或订阅令牌。

## 可选依赖

| 可选条件 | 何时需要 | 不具备时怎么办 |
| --- | --- | --- |
| PyPI 网络访问与 pip | 首次获取 `cryptography` 或 Frida 包。 | 包已安装或有匹配 Python/Windows 架构的离线 wheel 时无需联网；运行期间的核心控制与规则验收只访问本机回环地址。 |
| `pythonw.exe` | 维护器后台启动时避免控制台窗口。 | 安装脚本优先使用它；不存在时退回同环境 `python.exe` 并使用隐藏窗口的进程标志。 |

## 自检实际范围

`verify_dependencies.py` 会检查：

- 当前系统的 `os.name` 是否为 `nt`；
- `importlib.util.find_spec` 是否能发现当前 Python 环境中的 `cryptography` 和 `frida` 模块；这不是执行包导入或验证二进制扩展可用性；
- 当前环境发现不了 Frida 时，尝试在隔离 Python 子进程中真实导入已安装维护器 `lib` 目录中的 Frida；
- 当前用户默认 Aurora 配置路径是否为文件，以及 `os.access(..., os.R_OK)` 是否通过；不会读取或解密内容。

它不会检查 Python 最低版本、pip/PyPI 连通性、包版本兼容性、当前环境包能否真实导入、Aurora 进程和附加权限、两个本地 API、HKCU Run 写权限、登录启动是否有效、配置是否可解密、目标应用进程识别、订阅/节点或实际 TUN 连通性。配置解密与摘要由 `inspect` 验证；安装会再实际导入复制后的 Frida，并等待维护器报告活动规则匹配。完整完成标准仍须按[使用方式](usage.md#完成标准)单独验收。

## 修复方向

若配置文件不存在，确认当前 Windows 用户账号正确，并正常启动过 Aurora Slim。若只检查副本，自检不会自动改为检查 `--config` 指定路径，应直接对副本运行 `inspect`。若摘要或 JSON 校验失败，不要覆盖文件；这通常表示版本或格式已变化，应阅读 `references/aurora-format.md` 并重新进行只读调查。

若发现模块但实际导入失败，用同一个 `python` 执行 `python -c "import cryptography; import frida"` 查看错误，重新安装与当前 Python/Windows 架构匹配的包。自检通过不代表 API、hook 或代理链路已经可用。
