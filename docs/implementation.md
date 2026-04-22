# AutoProxy 实现说明

## 当前包含的能力

- OpenBao 代理源：读取 KV v2 记录，例如 `secret/autoproxy/proxies/proxy-001`。
- OpenBao JSON 导入：从本地 JSON 文件批量写入代理记录。
- 本地 TXT 代理源：保留为调试入口，按行读取代理 URI。
- `sub2api` 适配器：通过 `/api/v1/auth/login` 登录，查询 `/api/v1/admin/proxies`，并提交代理记录。
- Clash Verge 适配器：支持写入 YAML 或 Clash Verge 扩展脚本。默认推荐 YAML 模式，把导入代理 `B` 写成 `dialer-proxy: <first-hop>` 的链式节点，并为每条代理暴露一个本地 SOCKS listener。
- AdsPower 适配器：把上游代理导入 Proxy List，并创建使用本地 Clash SOCKS listener 的浏览器环境。
- Reporter：把 JSON 和 Markdown 执行报告写入 `docs/reports/`。

## 预期流程

1. 运行 `python3 autoproxy.py run --session-tag test001`。
2. 脚本读取配置中的 OpenBao `read_path`，并把数据规范化为代理记录。
3. 代理记录同步到 `sub2api`。
4. Clash Verge 配置被更新：导入代理 `B` 会变成 `auto-chain-*`，通过已配置的第一跳代理出站，并获得一个本地 SOCKS listener。
5. AdsPower 导入上游代理，并创建以代理 `name` 命名的 profile；profile 代理指向 `127.0.0.1:<listener_port>`。
6. 执行报告写入 `docs/reports/<date>/`。

## 本地接入前需要确认

- 复制 `config.openbao.example.json` 为 `config.local.json`，再填写本地服务地址和路径。
- CLI 默认按 `config.local.json`、`config.openbao.json`、`config.openbao.example.json` 的顺序读取配置。
- 配置中的相对路径按配置文件所在目录解析；Windows 下推荐在 JSON 里使用 `/` 或 `${USERPROFILE}` 形式。
- 文件读写统一使用 UTF-8，避免 Windows 中文环境下报告和配置乱码。
- 导出 `OPENBAO_TOKEN`，并让 `proxy_source.read_path` 指向要读取的 OpenBao 代理记录。
- 让 `proxy_source.import_prefix` 指向批量导入时要写入的目录，例如 `autoproxy/proxies`。
- 环境变量占位符支持 `${VAR}` 必填和 `${VAR:-default}` 可选默认值；OpenBao token 是导入和读取必需项。
- 导出 `SUB2API_EMAIL` 和 `SUB2API_PASSWORD`，或者直接提供 token。
- 如果你的 sub2api 部署和默认接口不同，需要确认代理创建接口和字段名。
- 更新 `configs/clash-verge-standard.yaml`，确保 `clash.base_proxy_name` 指向真实第一跳代理，例如 `hs2-US`。
- 推荐设置 `clash.write_mode=yaml`，并把 `clash.config_path` 指向 core 实际加载的配置文件。
- Windows 服务模式下，推荐配合 `clash.restart_after_write=true` 和 `Restart-Service clash_verge_service` 让新 listener 立即生效。
- 如果仍需使用 Clash Verge Rev 的增强配置链，再设置 `clash.write_mode=script`，并把 `profiles_path` / `profile_dir` 指向 Clash Verge 的配置目录。脚本会自动读取 `profiles.yaml` 当前 profile 的 `option.script`。
- YAML 模式如需通过 external controller 生效，开启 `clash.reload_after_write` 并配置 `clash.controller_url`。

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

适配器只管理 `auto-chain-` 前缀的代理、`AUTO-CHAIN` 策略组、`auto-listener-` 前缀的 listener，以及最终的 `MATCH,AUTO-CHAIN` 规则。用户自己的代理和非 `MATCH` 规则会保留。

推荐的 `yaml` 模式会直接修改当前运行配置，适合命令行自动化和服务重启。`script` 模式则会写入 Clash Verge 当前 profile 的扩展脚本，例如 `profiles/<script_uid>.js`。脚本里维护 `AUTOPROXY_MANAGED` 数组，并在 Clash Verge 生成最终 `clash-verge.yaml` 时注入代理、策略组、规则和 listener。这个模式适合 Clash Verge 使用增强配置或运行时生成配置的场景，但修改脚本后通常需要重新启用 Script。

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

如果使用 `yaml` 模式且 `clash.reload_after_write=true`，适配器会在原子写入后调用：

```http
PUT /configs?force=true
Content-Type: application/json

{"path": "<clash.config_path 的绝对路径>"}
```

这一步依赖 Clash / Mihomo 的 external controller。`clash.config_path` 必须是 core 当前正在使用的配置文件，否则 reload 后也不会加载新增 listener。

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

`openbao-get` 默认列出 `import_prefix` 下的全部代理。也可以指定单条：

```bash
python3 autoproxy.py openbao-get --id proxy-010
python3 autoproxy.py openbao-get --name devtest
```

写入类命令也支持指定单条代理：

```bash
python3 autoproxy.py sub2api-sync --id proxy-010
python3 autoproxy.py clash-write --name devtest
python3 autoproxy.py adspower-create-profile --id proxy-010
python3 autoproxy.py run --session-tag test001 --id proxy-010
```

不指定 `--id` / `--name` 时，这些命令使用 `read_path`。指定 `--name` 时必须精确匹配到唯一一条记录。

Windows PowerShell 下可以使用：

```powershell
py -3 .\autoproxy.py openbao-get
py -3 .\autoproxy.py run --session-tag test001
```

`sub2api` 和 AdsPower 在创建前会先尝试复用已有记录，避免重复测试时堆积相同代理或 profile。

## OpenBao 代理格式

代理记录存放在 KV v2 下：路径里使用稳定 ID，secret 数据里放一个可读的 `name`：

```bash
bao kv put secret/autoproxy/proxies/proxy-001 \
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
GET /v1/secret/data/autoproxy/proxies/proxy-001
X-Vault-Token: <token>
```

`name` 会用于生成节点名称，例如 `openbao-devtest` 和 `auto-chain-openbao-devtest`。

OpenBao 配置拆成两个路径：

```json
{
  "read_path": "autoproxy/proxies/proxy-001",
  "import_prefix": "autoproxy/proxies"
}
```

`read_path` 是需要单条代理的完整流程所读取的记录。`import_prefix` 是导入和列表查询目录，JSON 中不同 `id` 会写入不同条目，例如 `proxy-010` 会写入 `secret/autoproxy/proxies/proxy-010`。`openbao-get` 不指定参数时会列出 `import_prefix` 下全部代理。旧字段 `secret_path` 仅作为兼容旧配置保留。
