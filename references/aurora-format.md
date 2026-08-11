# Aurora Slim 配置格式参考

仅在 Aurora 更新、配置校验失败或需要支持其他版本时读取本页。

## 已验证范围

- Windows 版 Aurora Slim `5.2.4`。
- 配置目录：`%USERPROFILE%\.aurora-slim\`。
- 配置文件名：`.` 加 `SHA1("APPDATA.CONFIG.FILENAME.AIRPORT")`，当前结果为 `.a80ac3211ccf83b91dffd138706f16d66660dfe8`。
- 已验证嵌套配置键：`global_tun_config`、`tun_config`。

Aurora 更新后不得假定格式仍然一致。先运行 `inspect`；摘要失败、键缺失或路由结构变化时停止，不要尝试写入。

## 文件结构

文件由两个 AES-CFB 块连续组成：

| 偏移 | 内容 |
| --- | --- |
| 前 80 字节 | 16 字节 IV，加密后的 64 字节 ASCII SHA-256 十六进制摘要。 |
| 其余字节 | 16 字节 IV，加密后的 UTF-8 JSON。 |

解密 JSON 后，以原始明文字节计算 SHA-256，结果必须和第一个块解密出的 64 字节摘要完全一致。重新加密时为两个块分别生成随机 16 字节 IV。

加密常量来自 Aurora 客户端自身的本地实现，不是用户账号、订阅或节点凭据。脚本只使用它们解析该客户端的本地配置，不输出解密后的完整 JSON。

## 路由结构

`global_tun_config` 与 `tun_config` 在顶层配置中通常保存为 JSON 字符串。内部结构使用 `route.rules`：

```json
{
  "route": {
    "rules": [
      {
        "inbound": "tun-in",
        "process_name": ["example.exe"],
        "outbound": "direct"
      },
      {
        "outbound": "Proxy"
      }
    ]
  }
}
```

脚本只修改第一个同时满足以下条件的规则：

- `outbound` 等于 `direct`；
- `process_name` 已存在且为数组。

未匹配的最后兜底规则保持 `Proxy`，因此 ChatGPT 等其他流量继续使用全局代理。脚本不根据域名、IP 或安装路径生成额外规则。

## 调查方法

如需重新确认其他 Aurora 版本，按以下顺序进行只读调查：

1. 记录客户端版本、前端进程、后端进程和 TUN 网卡名称。
2. 从实际运行进程确认目标程序的可执行文件名及子进程。
3. 备份配置目录，并比较切换模式前后的文件变化。
4. 从客户端二进制中的配置读写路径确认文件名派生、摘要和加密实现。
5. 只在副本上完成解密、摘要校验、重加密和 round-trip 测试。
6. 确认路由规则语义后，才允许对已备份的真实配置执行写入。

不要把反编译产物、用户配置、节点信息或备份提交到 Skill 仓库。

