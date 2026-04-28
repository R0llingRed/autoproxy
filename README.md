# AutoProxy

AutoProxy 是一个本地代理自动化工具，用于把 OpenBao 中的代理信息同步到 sub2api、Clash Verge、AdsPower 和 Camoufox。

## 功能

- 从 OpenBao KV v2 读取代理信息。
- 支持从 JSON 文件批量写入代理到 OpenBao。
- 将代理同步到 sub2api 代理库。
- 将代理写入 Clash Verge 配置，生成链式代理和本地 SOCKS 端口。
- 在 AdsPower 中添加代理，并创建使用本地 SOCKS 端口的浏览器环境。
- 可选启动 Camoufox 本地指纹浏览器，并复用 Clash 本地 SOCKS 端口。
- 每个模块都可以单独执行，方便调试。

## 流程

```text
OpenBao
  -> sub2api
  -> Clash Verge 本地 SOCKS listener
  -> AdsPower profile / Camoufox profile
```

AdsPower 和 Camoufox 都不直接使用上游代理，而是使用 Clash 暴露的本地 SOCKS 端口。

## 环境要求

- Python 3.11+
- OpenBao，本地示例地址：`http://127.0.0.1:8200`
- sub2api
- Clash Verge / Mihomo
- AdsPower，本地 API 示例地址：`http://127.0.0.1:50325`
- Camoufox，可选，仅在使用 `camoufox-*` 命令或 `browser=camoufox` 时需要

Windows、macOS、Linux 都可以运行本脚本。Windows 下建议使用 PowerShell 和 Python Launcher：

```powershell
py -3 --version
py -3 -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m pip install -r requirements.txt
```

如果要使用 Camoufox，请安装可选依赖并下载浏览器：

```bash
python3 -m pip install -e ".[camoufox]"
python3 -m camoufox fetch
```

## 配置

主要配置文件是：

```text
config.openbao.example.json
```

建议复制一份作为本地配置：

```bash
cp config.openbao.example.json config.local.json
```

Windows PowerShell：

```powershell
Copy-Item config.openbao.example.json config.local.json
```

默认情况下，CLI 会按顺序读取：

```text
config.local.json -> config.openbao.json -> config.openbao.example.json
```

因此日常使用时通常不需要传 `--config`。如果要指定其他配置文件，再使用 `--config <path>`。

配置文件里的相对路径会按配置文件所在目录解析，不依赖当前终端所在目录。路径建议使用 `/`，Python 在 Windows 下也能识别，例如：

```json
{
  "clash": {
    "config_path": "configs/clash-verge-standard.yaml"
  },
  "report_base_dir": "docs"
}
```

如果要引用用户目录，推荐使用 `${VAR}` 占位符：

```json
{
  "clash": {
    "config_path": "${USERPROFILE}/AppData/Roaming/io.github.clash-verge-rev.clash-verge-rev/profiles/autoproxy.yaml"
  }
}
```

推荐把敏感配置写进项目根目录 `.env`，这样不需要每次手动注入环境变量：

```dotenv
OPENBAO_TOKEN=your-openbao-token
OPENBAO_CA_CERT_PATH=D:/whfiles/openbao/certs/ca.crt
SUB2API_EMAIL=admin@sub2api.local
SUB2API_PASSWORD=your-password
ADSPOWER_API_KEY=
CAMOUFOX_WINDOW=1440x900
```

CLI 会在读取配置文件前，自动加载配置文件所在目录下的 `.env`。

如果你不想使用 `.env`，也可以继续手动设置环境变量：

```bash
export OPENBAO_TOKEN='...'
export OPENBAO_CA_CERT_PATH='/path/to/openbao-ca.pem'
export SUB2API_EMAIL='admin@sub2api.local'
export SUB2API_PASSWORD='...'
export ADSPOWER_API_KEY='...'
```

Windows PowerShell：

```powershell
$env:OPENBAO_TOKEN = "..."
$env:OPENBAO_CA_CERT_PATH = "D:/whfiles/openbao/certs/ca.crt"
$env:SUB2API_EMAIL = "admin@sub2api.local"
$env:SUB2API_PASSWORD = "..."
$env:ADSPOWER_API_KEY = "..."
```

如果环境变量没有设置，程序会直接报错。

占位符规则：

- `${OPENBAO_TOKEN}` 表示必填，缺失会报错。
- `${OPENBAO_CA_CERT_PATH:-}` 表示可选，用于 HTTPS 自签 CA 证书链校验。
- `${SUB2API_TOKEN:-}` 表示可选，缺失时使用空字符串。
- `${HOST:-127.0.0.1}` 表示可选，缺失时使用默认值。

如果 OpenBao 配的是自签证书，建议把 CA 证书导出成 PEM 文件，并通过 `OPENBAO_CA_CERT_PATH` 或 `proxy_source.ca_cert_path` 传给项目。不要直接关闭 TLS 校验。

## OpenBao 数据格式

推荐将所有代理统一存到一个 OpenBao KV v2 secret：

```bash
bao kv put secret/external/proxies \
  proxies:='{
    "proxy-001": {
      "name": "devtest",
      "type": "socks5",
      "host": "1.2.3.4",
      "port": 5678,
      "username": "testuser",
      "password": "testpass",
      "country": "US",
      "updated_at": "2026-04-21T10:30:00Z",
      "updated_by": "user"
    }
  }'
```

`name` 会用于生成 sub2api、Clash 和 AdsPower 中的名称。
`updated_at` 和 `updated_by` 会在导入时自动补齐；`updated_by` 目前只区分 `user` 和 `system`。

配置里 OpenBao 路径分成两个字段：

```json
{
  "proxy_source": {
    "read_path": "external/proxies",
    "import_prefix": "external/proxies"
  }
}
```

- `read_path` 和 `import_prefix` 都指向共享集合 key。
- 例如 JSON 里有 `{"id": "proxy-010", ...}`，会写入 `secret/external/proxies` 下的 `proxies.proxy-010`。
- 旧字段 `secret_path` 仍兼容，但不再推荐。

## JSON 导入 OpenBao

示例文件：

```text
examples/openbao-proxies.example.json
```

导入命令：

```bash
python3 autoproxy.py openbao-import --file examples/openbao-proxies.example.json
```

Windows PowerShell：

```powershell
py -3 .\autoproxy.py openbao-import --file examples/openbao-proxies.example.json
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

列出 `secret/external/proxies` 里的全部代理：

```bash
python3 autoproxy.py openbao-get
```

读取指定 ID：

```bash
python3 autoproxy.py openbao-get --id proxy-010
```

按名称精确匹配：

```bash
python3 autoproxy.py openbao-get --name devtest
```

搜索任意字段，返回包含关键词的完整条目：

```bash
python3 autoproxy.py openbao-grep "011"
python3 autoproxy.py openbao-grep "devtest"
```

同步到 sub2api：

```bash
python3 autoproxy.py sub2api-sync
python3 autoproxy.py sub2api-sync --id proxy-010
python3 autoproxy.py sub2api-sync --name devtest
```

写入 Clash Verge 配置：

```bash
python3 autoproxy.py clash-write
python3 autoproxy.py clash-write --id proxy-010
python3 autoproxy.py clash-write --name devtest
```

添加到 AdsPower 代理库：

```bash
python3 autoproxy.py adspower-add-proxy
python3 autoproxy.py adspower-add-proxy --id proxy-010
python3 autoproxy.py adspower-add-proxy --name devtest
```

创建 AdsPower 环境：

```bash
python3 autoproxy.py adspower-create-profile
python3 autoproxy.py adspower-create-profile --id proxy-010
python3 autoproxy.py adspower-create-profile --name devtest
```

启动 Camoufox 本地浏览器：

```bash
python3 autoproxy.py camoufox-launch --id proxy-010
python3 autoproxy.py camoufox-launch --name devtest
python3 autoproxy.py camoufox-launch --id proxy-010 --template desktop-humanized
```

`camoufox-launch` 会先写入 Clash 本地 SOCKS listener，再用该 listener 启动 Camoufox。默认打开：

```text
https://www.browserscan.net
```

如果你想固定窗口尺寸，可以在 `.env` 里增加：

```dotenv
CAMOUFOX_WINDOW=1280x720
```

然后在 `config.local.json` 的 `camoufox.window` 使用 `${CAMOUFOX_WINDOW:-1280x720}`。项目会把它解析成 Camoufox 的 `window=(1280, 720)`。如果想交给 Camoufox 自动生成窗口，设置为 `auto`。

默认 `geoip=true` 会让 Camoufox 通过当前代理自动匹配经纬度、时区和语言。只有确实需要手动覆盖时，再设置：

```dotenv
CAMOUFOX_TIMEZONE=America/Los_Angeles
```

查询 Camoufox 本地模板：

```bash
python3 autoproxy.py camoufox-templates
python3 autoproxy.py camoufox-templates --name desktop-humanized
```

查询 Camoufox 本地代理/profile 绑定信息：

```bash
python3 autoproxy.py camoufox-profiles
python3 autoproxy.py camoufox-profiles --id proxy-010
```

批量创建 sub2api API key：

```bash
python3 autoproxy.py sub2api-keys-bulk --file sub2api-keys.txt
```

`sub2api-keys.txt` 使用 UTF-8 编码，每行一条：

```text
test-a,1
test-b,2
```

格式固定为 `name,group-id`，允许空行，`#` 开头的行会被忽略。

执行完整流程：

```bash
python3 autoproxy.py run
python3 autoproxy.py run --id proxy-010
python3 autoproxy.py run --name devtest
python3 autoproxy.py run --id proxy-010 --browser camoufox
```

`run` 不再要求手动传 `--session-tag`。如果省略，报告文件会默认使用当前时间小时标签，例如 `2026-04-24-17.json` 和 `2026-04-24-17.md`。

`openbao-get` 默认会列出共享 key 里的全部代理。其余读取或执行类命令在共享 key 中存在多条代理时，建议显式传 `--id` 或 `--name`；指定 `--name` 时必须精确匹配到唯一一条代理，避免同名误用。

Windows 下把 `python3 autoproxy.py` 换成 `py -3 .\autoproxy.py` 即可。

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
AdsPower / Camoufox -> 127.0.0.1:7892 -> Clash -> hs2-US -> 导入代理
```

每条代理会占用一个本地 SOCKS 端口，从 `listener_start_port` 开始递增。

默认推荐使用 `yaml` 模式，直接修改 Clash 当前实际运行的配置文件，然后重启或 reload 内核。这个模式更适合命令行自动化，不依赖 Clash Verge Rev 的 Script 重新启用动作：

```json
{
  "clash": {
    "write_mode": "yaml",
    "base_proxy_name": "hs2-US",
    "listener_start_port": 7892,
    "config_path": "${CLASH_VERGE_HOME}/clash-verge.yaml",
    "restart_after_write": true,
    "restart_strategy": "mihomo",
    "mihomo_executable": "D:/Program Files/Clash Verge/verge-mihomo.exe",
    "mihomo_home": "${CLASH_VERGE_HOME}",
    "restart_wait_seconds": 2.0
  }
}
```

macOS 示例：

```bash
export CLASH_VERGE_HOME="$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev"
```

执行 `clash-write` 后，会优先修改 `config_path`，然后按 `restart_strategy` 重启内核，随后检查端口：

```bash
python3 autoproxy.py clash-write --id proxy-010
nc -vz 127.0.0.1 7892
```

Windows 上推荐使用内置的 `mihomo` 重启策略，不再把复杂 PowerShell 写进 JSON。该策略会执行：

- `taskkill /IM verge-mihomo.exe /F`
- `verge-mihomo.exe -d <mihomo_home> -f <config_path> -ext-ctl-pipe \\.\pipe\verge-mihomo`

```json
{
  "clash": {
    "config_path": "${CLASH_VERGE_HOME}/clash-verge.yaml",
    "restart_after_write": true,
    "restart_strategy": "mihomo",
    "mihomo_executable": "D:/Program Files/Clash Verge/verge-mihomo.exe",
    "mihomo_home": "${CLASH_VERGE_HOME}"
  }
}
```

如果你仍然需要自定义命令，可以改回 `command` 策略：

```json
{
  "clash": {
    "restart_after_write": true,
    "restart_strategy": "command",
    "restart_command": [
      "your-command",
      "arg1"
    ]
  }
}
```

`restart_command` 是字符串数组，`clash-write` 写入成功后会直接执行。推荐只在你自己的受控环境中启用。

如果你确实需要继续使用 Clash Verge Rev 的增强配置链，也保留 `script` 模式支持。但要注意：修改 `Script` 配置后，Clash Verge Rev 通常需要重新启用该 Script，单纯重启 Mihomo 内核不一定会重新应用脚本。

## Clash Reload

如果你不想重启服务，也可以在 `yaml` 模式下开启 external controller reload：

```json
{
  "clash": {
    "write_mode": "yaml",
    "config_path": "configs/clash-verge-standard.yaml",
    "reload_after_write": true,
    "controller_url": "http://127.0.0.1:9090",
    "controller_secret": "",
    "reload_force": true
  }
}
```

关键点：

- `config_path` 必须指向 Clash Verge 当前正在使用的配置文件，而不是一份普通模板。
- 如果未配置 `config_path`，程序会从 `profiles.yaml` 找到当前 `local` profile 的 YAML 文件。
- reload 请求会把 `config_path` 转成绝对路径后调用 `PUT /configs?force=true`。
- 如果 Clash external controller 设置了 secret，请填写 `controller_secret`，或者写成 `${CLASH_CONTROLLER_SECRET}` 并设置环境变量。
- 如果 Clash Verge 使用增强配置或运行时合并配置，需要确认 core 实际加载的是哪个 profile 文件。
- reload 只负责让配置生效；如果旧连接需要断开，后续可以再扩展 `DELETE /connections`。

## 注意事项

- AdsPower 免费版只有 2 个环境，超过会创建失败。
- 默认推荐用 Clash `yaml` 模式做自动化；`script` 模式保留给需要依赖 Clash Verge Rev 增强配置链的场景。
- 当前 OpenBao 使用单一共享 key `secret/external/proxies`；读取时按 `id` 或 `name` 从 `proxies` 对象中选中单条，批量导入会更新同一个 key 下的多个子项。
- sub2api 和 AdsPower 会尽量复用已有记录，避免重复创建。
- Windows 下请确认 Clash Verge / AdsPower / OpenBao 的本地 API 端口允许当前用户访问。
- 所有 JSON、YAML、报告文件按 UTF-8 读写，避免 Windows 中文环境下乱码。
- 文档统一使用中文；功能更新时请同步更新本 README。
