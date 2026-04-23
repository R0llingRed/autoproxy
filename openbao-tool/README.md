# OpenBao 代理导入与查询工具

这个目录是从 AutoProxy 项目里单独提取出来的 OpenBao 小工具，用于给同事导入和查看代理信息。它只依赖 Python 和 `requests`，不依赖 AutoProxy 项目的其他代码。

## 文件说明

- `openbao_tool.py`：独立命令行脚本。
- `config.openbao.example.json`：精简配置示例，只包含 OpenBao 连接信息。
- `README.md`：当前说明文档。

## 环境要求

- Python 3.11+
- Python 包：`requests`
- OpenBao KV v2，默认 mount 是 `secret`，默认代理路径是 `external/proxies`

安装依赖：

```bash
python3 -m pip install requests
```

Windows PowerShell：

```powershell
py -3 -m pip install requests
```

## 配置方式

建议复制一份本地配置，不要直接改示例文件：

```bash
cp config.openbao.example.json config.openbao.json
```

Windows PowerShell：

```powershell
Copy-Item config.openbao.example.json config.openbao.json
```

然后设置环境变量：

```bash
export OPENBAO_BASE_URL="https://127.0.0.1:8200"
export OPENBAO_TOKEN="your-openbao-token"
export OPENBAO_CA_CERT_PATH="/path/to/ca.pem"
```

Windows PowerShell：

```powershell
$env:OPENBAO_BASE_URL = "https://127.0.0.1:8200"
$env:OPENBAO_TOKEN = "your-openbao-token"
$env:OPENBAO_CA_CERT_PATH = "D:/path/to/ca.pem"
```

如果 OpenBao 不是自签证书，`OPENBAO_CA_CERT_PATH` 可以不设置。也可以把这些变量写到同目录的 `.env` 文件里，脚本读取配置时会自动加载。

## 数据格式

工具默认读写 OpenBao KV v2 的这个位置：

```text
secret/external/proxies
```

其中实际写入的 secret data 结构是：

```json
{
  "proxies": {
    "proxy-001": {
      "name": "devtest",
      "type": "socks5",
      "host": "1.2.3.4",
      "port": 5678,
      "username": "testuser",
      "password": "testpass",
      "country": "US"
    }
  }
}
```

导入文件可以是单个对象：

```json
{
  "id": "proxy-010",
  "name": "file-proxy-1",
  "type": "socks5",
  "host": "1.2.3.4",
  "port": 5678,
  "username": "testuser",
  "password": "testpass"
}
```

也可以是数组：

```json
[
  {
    "id": "proxy-010",
    "name": "file-proxy-1",
    "type": "socks5",
    "host": "1.2.3.4",
    "port": 5678
  },
  {
    "id": "proxy-011",
    "name": "file-proxy-2",
    "raw_uri": "socks5://user:pass@5.6.7.8:6789"
  }
]
```

导入时会自动补充 `updated_at` 和 `updated_by` 字段。`id` 不会写入代理内容本身，而是作为 `proxies` 下面的 key。

## 常用命令

列出全部代理：

```bash
python3 openbao_tool.py get --config config.openbao.json
```

兼容原项目命令名：

```bash
python3 openbao_tool.py openbao-get --config config.openbao.json
```

按 ID 查询：

```bash
python3 openbao_tool.py get --id proxy-010 --config config.openbao.json
```

按名称精确查询：

```bash
python3 openbao_tool.py get --name devtest --config config.openbao.json
```

搜索任意字段：

```bash
python3 openbao_tool.py grep devtest --config config.openbao.json
python3 openbao_tool.py openbao-grep "011" --config config.openbao.json
```

导入 JSON 文件：

```bash
python3 openbao_tool.py import --file proxies.json --config config.openbao.json
python3 openbao_tool.py openbao-import --file proxies.json --config config.openbao.json
```

如果不想写配置文件，也可以直接传参数：

```bash
python3 openbao_tool.py get \
  --base-url https://127.0.0.1:8200 \
  --token "$OPENBAO_TOKEN" \
  --mount secret \
  --path external/proxies
```

Windows 下把 `python3 openbao_tool.py` 换成 `py -3 .\openbao_tool.py` 即可。

## 注意事项

- 该工具使用 OpenBao KV v2 API，请确认 mount 确实是 KV v2。
- 自签 HTTPS 证书建议通过 `OPENBAO_CA_CERT_PATH` 或 `ca_cert_path` 配置 CA 文件，不建议关闭 TLS 校验。
- `get --name` 是精确匹配，可能返回多条同名代理。
- `import` 会先读取当前集合，再把导入内容合并写回同一个 secret。
- 导入同名 `id` 会覆盖 OpenBao 中已有的对应代理。
