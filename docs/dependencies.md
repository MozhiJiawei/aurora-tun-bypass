# 依赖说明

## 检查命令

在 workspace 根目录运行：

```powershell
python skills/aurora-tun-bypass/verify_dependencies.py
```

## 必需依赖

| 依赖 | 用途 | 缺失时的处理 |
| --- | --- | --- |
| Windows | Aurora Slim 与隐藏文件属性处理。 | 在安装 Aurora 的 Windows 用户会话中运行。 |
| Python 3.10+ | 执行依赖检查和配置脚本。 | 安装受支持的 Python 3。 |
| `cryptography` | AES-CFB 解密、加密与摘要验证。 | 运行 `python -m pip install cryptography`。 |
| Aurora Slim 本地配置 | inspect、patch 和 restore 的输入。 | 先正常安装并至少运行一次 Aurora Slim。 |

脚本不需要 Aurora 账号密码、订阅令牌、管理员权限或网络访问。

## 自检范围

`verify_dependencies.py` 会检查：

- 当前系统是否为 Windows；
- Python 是否能导入 `cryptography`；
- 当前用户目录下是否存在且可读取已知的 Aurora 配置文件。

它不会检查：

- Aurora 账号、订阅或节点是否有效；
- 目标应用真实使用了哪些进程；
- TUN 连接当前是否成功；
- 其他 Aurora 版本是否仍使用相同格式；
- 配置内容是否可解密。最后一项由 `inspect` 完成。

## 修复方向

若配置文件不存在，先确认正在正确的 Windows 用户账号下运行，并正常启动过 Aurora Slim。若摘要或 JSON 校验失败，不要覆盖文件；这通常表示 Aurora 版本或格式已变化，应阅读 `references/aurora-format.md` 并重新进行只读调查。

