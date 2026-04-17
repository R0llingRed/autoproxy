# AutoProxy 实现说明

## 当前包含的能力

- OpenBao 代理源：读取 KV v2 记录，例如 `secret/autoproxy/proxies/proxy-002`。
- OpenBao JSON 导入：从本地 JSON 文件批量写入代理记录。
- 本地 TXT 代理源：保留为调试入口，按行读取代理 URI。
- `sub2api` 适配器：通过 `/api/v1/auth/login` 登录，查询 `/api/v1/admin/proxies`，并提交代理记录。
- Clash Verge 适配器：读取 YAML，保留已配置的第一跳代理，把导入代理 `B` 写成 `dialer-proxy: <first-hop>` 的链式节点，并为每条代理暴露一个本地 SOCKS listener。
- AdsPower 适配器：把上游代理导入 Proxy List，并创建使用本地 Clash SOCKS listener 的浏览器环境。
- Reporter：把 JSON 和 Markdown 执行报告写入 `docs/reports/`。

## 预期流程

1. 运行 `python3 autoproxy.py run --session-tag test001`。
2. 脚本读取配置中的 OpenBao secret path，并把数据规范化为代理记录。
3. 代理记录同步到 `sub2api`。
4. Clash Verge 配置被更新：导入代理 `B` 会变成 `auto-chain-*`，通过已配置的第一跳代理出站，并获得一个本地 SOCKS listener。
5. AdsPower 导入上游代理，并创建以代理 `name` 命名的 profile；profile 代理指向 `127.0.0.1:<listener_port>`。
6. 执行报告写入 `docs/reports/<date>/`。

## 本地接入前需要确认

- 复制 `config.openbao.example.json` 为 `config.local.json`，再填写本地服务地址和路径。
- CLI 默认按 `config.local.json`、`config.openbao.json`、`config.openbao.example.json` 的顺序读取配置。
- 配置中的相对路径按配置文件所在目录解析；Windows 下推荐在 JSON 里使用 `/` 或 `${USERPROFILE}` 形式。
- 文件读写统一使用 UTF-8，避免 Windows 中文环境下报告和配置乱码。
- 导出 `OPENBAO_TOKEN`，并让 `proxy_source.secret_path` 指向要读取的 OpenBao 代理记录。
- 导出 `SUB2API_EMAIL` 和 `SUB2API_PASSWORD`，或者直接提供 token。
- 如果你的 sub2api 部署和默认接口不同，需要确认代理创建接口和字段名。
- 更新 `configs/clash-verge-standard.yaml`，确保 `clash.base_proxy_name` 指向真实第一跳代理，例如 `hs2-US`。
- 如果要直接写入真实 Clash Verge 配置，把 `clash.config_path` 指向真实 profile 文件。

## Clash 链路形态

受管链路固定为：

```text
client -> first-hop -> B -> target
```

配置中的第一跳代理必须已经存在于 Clash 配置中。导入代理 `B` 会写成：

```yaml
- name: auto-chain-...
  type: socks5
  server: ...
  port: ...
  username: ...
  password: ...
  dialer-proxy: hs2-US
```

适配器只管理 `auto-chain-` 前缀的代理、`AUTO-CHAIN` 策略组，以及最终的 `MATCH,AUTO-CHAIN` 规则。用户自己的代理和非 `MATCH` 规则会保留。

每条导入代理都会获得一个受管 SOCKS listener。端口从 `clash.listener_start_port` 开始，每条递增 1：

```yaml
listeners:
  - name: auto-listener-openbao-devtest
    type: socks
    listen: 127.0.0.1
    port: 7890
    proxy: auto-chain-openbao-devtest
  - name: auto-listener-openbao-local-socks
    type: socks
    listen: 127.0.0.1
    port: 7891
    proxy: auto-chain-openbao-local-socks
```

AdsPower profile 指向这些本地 SOCKS listener，而不是直接指向上游代理。

## CLI 命令

每个模块都可以单独运行：

```bash
python3 autoproxy.py --config config.openbao.example.json openbao-get
python3 autoproxy.py --config config.openbao.example.json openbao-import --file examples/openbao-proxies.example.json
python3 autoproxy.py --config config.openbao.example.json sub2api-sync
python3 autoproxy.py --config config.openbao.example.json clash-write
python3 autoproxy.py --config config.openbao.example.json adspower-add-proxy
python3 autoproxy.py --config config.openbao.example.json adspower-create-profile
python3 autoproxy.py --config config.openbao.example.json run --session-tag test001
```

如果当前目录存在 `config.local.json`，上面的 `--config ...` 可以省略。

Windows PowerShell 下可以使用：

```powershell
py -3 .\autoproxy.py openbao-get
py -3 .\autoproxy.py run --session-tag test001
```

`sub2api` 和 AdsPower 在创建前会先尝试复用已有记录，避免重复测试时堆积相同代理或 profile。

## OpenBao 代理格式

代理记录存放在 KV v2 下：路径里使用稳定 ID，secret 数据里放一个可读的 `name`：

```bash
bao kv put secret/autoproxy/proxies/proxy-002 \
  name=devtest \
  type=socks5 \
  host=1.2.3.4 \
  port=5678 \
  username=testuser \
  password=test123 \
  country=US
```

脚本通过下面的 API 读取：

```http
GET /v1/secret/data/autoproxy/proxies/proxy-002
X-Vault-Token: <token>
```

`name` 会用于生成节点名称，例如 `openbao-devtest` 和 `auto-chain-openbao-devtest`。
