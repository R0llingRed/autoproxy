# AutoProxy

AutoProxy 是一个本地代理自动化工具，用于把 OpenBao 中的代理信息同步到 sub2api、Clash Verge 和 AdsPower。

## 功能

- 从 OpenBao KV v2 读取代理信息。
- 支持从 JSON 文件批量写入代理到 OpenBao。
- 将代理同步到 sub2api 代理库。
- 将代理写入 Clash Verge 配置，生成链式代理和本地 SOCKS 端口。
- 在 AdsPower 中添加代理，并创建使用本地 SOCKS 端口的浏览器环境。
- 每个模块都可以单独执行，方便调试。

## 流程

```text
OpenBao
  -> sub2api
  -> Clash Verge 本地 SOCKS listener
  -> AdsPower profile
```

AdsPower 不直接使用上游代理，而是使用 Clash 暴露的本地 SOCKS 端口。

## 环境要求

- Python 3.11+
- OpenBao，本地示例地址：`http://127.0.0.1:8200`
- sub2api
- Clash Verge / Mihomo
- AdsPower，本地 API 示例地址：`http://127.0.0.1:50325`

## 配置

主要配置文件是：

```text
config.openbao.example.json
```

建议复制一份作为本地配置：

```bash
cp config.openbao.example.json config.local.json
```

默认情况下，CLI 会按顺序读取：

```text
config.local.json -> config.openbao.json -> config.openbao.example.json
```

因此日常使用时通常不需要传 `--config`。如果要指定其他配置文件，再使用 `--config <path>`。

需要设置环境变量：

```bash
export OPENBAO_TOKEN='...'
export SUB2API_EMAIL='admin@sub2api.local'
export SUB2API_PASSWORD='...'
export ADSPOWER_API_KEY='...'
```

如果环境变量没有设置，程序会直接报错。

## OpenBao 数据格式

推荐每条代理存一条 OpenBao KV v2 secret：

```bash
bao kv put secret/autoproxy/proxies/proxy-001 \
  name=devtest \
  type=socks5 \
  host=1.2.3.4 \
  port=5678 \
  username=testuser \
  password=testpass \
  country=US
```

`name` 会用于生成 sub2api、Clash 和 AdsPower 中的名称。

## JSON 导入 OpenBao

示例文件：

```text
examples/openbao-proxies.example.json
```

导入命令：

```bash
python3 autoproxy.py openbao-import --file examples/openbao-proxies.example.json
```

JSON 可以是单个对象：

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

## 常用命令

读取 OpenBao 当前配置中的代理：

```bash
python3 autoproxy.py openbao-get
```

同步到 sub2api：

```bash
python3 autoproxy.py sub2api-sync
```

写入 Clash Verge 配置：

```bash
python3 autoproxy.py clash-write
```

添加到 AdsPower 代理库：

```bash
python3 autoproxy.py adspower-add-proxy
```

创建 AdsPower 环境：

```bash
python3 autoproxy.py adspower-create-profile
```

执行完整流程：

```bash
python3 autoproxy.py run --session-tag test001
```

## Clash 链式代理

配置里需要已有第一跳代理，例如：

```json
"base_proxy_name": "hs2-US"
```

导入代理后，会生成：

```yaml
auto-chain-openbao-devtest:
  dialer-proxy: hs2-US
```

实际链路：

```text
AdsPower -> 127.0.0.1:7890 -> Clash -> hs2-US -> 导入代理
```

每条代理会占用一个本地 SOCKS 端口，从 `listener_start_port` 开始递增。

## 注意事项

- AdsPower 免费版只有 2 个环境，超过会创建失败。
- 当前会写 Clash 配置文件，但不会自动 reload Clash。
- 当前 OpenBao 主流程一次读取一个 `secret_path`。
- sub2api 和 AdsPower 会尽量复用已有记录，避免重复创建。
- 文档统一使用中文；功能更新时请同步更新本 README。
