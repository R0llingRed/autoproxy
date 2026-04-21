from pathlib import Path

import pytest
import yaml

from autoproxy.adapters.clash_adapter import ClashVergeAdapter
from autoproxy.models import ProxyRecord


class FakeResponse:
    def __init__(self, payload=None, status_code=204):
        self._payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def put(self, url, *, json, headers, timeout):
        self.calls.append(("PUT", url, json, headers, timeout))
        return FakeResponse()


def base_config() -> str:
    return """
mixed-port: 7890
allow-lan: true
mode: rule
proxies:
  - name: A
    type: socks5
    server: 10.0.0.1
    port: 1080
    username: a-user
    password: a-pass
proxy-groups:
  - name: MANUAL
    type: select
    proxies:
      - A
rules:
  - MATCH,MANUAL
"""


def test_clash_adapter_adds_proxy_b_as_chained_exit_via_a():
    adapter = ClashVergeAdapter(base_proxy_name="A")
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
        provider="txt",
    )

    updated = adapter.merge_config(base_config(), record)
    parsed = yaml.safe_load(updated)

    proxies = {item["name"]: item for item in parsed["proxies"]}
    chain_name = "auto-chain-txt-proxy-b"

    assert proxies["A"]["server"] == "10.0.0.1"
    assert proxies[chain_name]["server"] == "1.2.3.4"
    assert proxies[chain_name]["port"] == 5678
    assert proxies[chain_name]["dialer-proxy"] == "A"

    groups = {item["name"]: item for item in parsed["proxy-groups"]}
    assert groups["AUTO-CHAIN"]["type"] == "select"
    assert groups["AUTO-CHAIN"]["proxies"] == [chain_name]
    assert parsed["rules"] == ["MATCH,AUTO-CHAIN"]


def test_clash_adapter_replaces_existing_managed_chain_node_only():
    adapter = ClashVergeAdapter(base_proxy_name="A")
    record = ProxyRecord.from_uri(
        "socks5://new:newpass@5.6.7.8:6789",
        proxy_id="proxy-c",
        provider="txt",
    )
    current = """
mixed-port: 7890
proxies:
  - name: A
    type: socks5
    server: 10.0.0.1
    port: 1080
  - name: auto-chain-txt-old
    type: socks5
    server: 9.9.9.9
    port: 9999
    dialer-proxy: A
  - name: user-owned
    type: http
    server: 8.8.8.8
    port: 8080
proxy-groups:
  - name: AUTO-CHAIN
    type: select
    proxies:
      - auto-chain-txt-old
"""

    updated = adapter.merge_config(current, record)
    parsed = yaml.safe_load(updated)
    proxy_names = [item["name"] for item in parsed["proxies"]]

    assert "auto-chain-txt-old" in proxy_names
    assert "auto-chain-txt-proxy-c" in proxy_names
    assert "user-owned" in proxy_names


def test_clash_adapter_refreshes_existing_managed_chain_nodes_to_current_base_proxy():
    adapter = ClashVergeAdapter(base_proxy_name="new-hop")
    record = ProxyRecord.from_uri(
        "socks5://new:newpass@5.6.7.8:6789",
        proxy_id="proxy-c",
        provider="txt",
    )
    current = """
mixed-port: 7890
proxies:
  - name: new-hop
    type: socks5
    server: 10.0.0.1
    port: 1080
  - name: auto-chain-txt-old
    type: socks5
    server: 9.9.9.9
    port: 9999
    dialer-proxy: old-hop
  - name: user-owned
    type: http
    server: 8.8.8.8
    port: 8080
proxy-groups:
  - name: AUTO-CHAIN
    type: select
    proxies:
      - auto-chain-txt-old
"""

    updated = adapter.merge_config(current, record)
    parsed = yaml.safe_load(updated)
    proxies = {item["name"]: item for item in parsed["proxies"]}

    assert proxies["auto-chain-txt-old"]["dialer-proxy"] == "new-hop"
    assert proxies["auto-chain-txt-proxy-c"]["dialer-proxy"] == "new-hop"
    assert proxies["user-owned"]["server"] == "8.8.8.8"


def test_clash_adapter_adds_listener_ports_incrementally():
    adapter = ClashVergeAdapter(base_proxy_name="A", listener_start_port=7890)
    first = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="first",
        provider="txt",
        name="devtest",
    )
    second = ProxyRecord.from_uri(
        "socks5://198.51.100.30:1080",
        proxy_id="second",
        provider="openbao",
        name="local-socks",
    )

    first_config = adapter.merge_config(base_config(), first)
    second_config = adapter.merge_config(first_config, second)
    parsed = yaml.safe_load(second_config)

    listeners = {item["name"]: item for item in parsed["listeners"]}
    assert listeners["auto-listener-txt-devtest"]["port"] == 7890
    assert listeners["auto-listener-openbao-local-socks"]["port"] == 7891
    assert listeners["auto-listener-openbao-local-socks"]["proxy"] == "auto-chain-openbao-local-socks"


def test_clash_adapter_reuses_existing_listener_port_for_same_proxy():
    adapter = ClashVergeAdapter(base_proxy_name="A", listener_start_port=7890)
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="first",
        provider="txt",
        name="devtest",
    )

    first_config = adapter.merge_config(base_config(), record)
    second_config = adapter.merge_config(first_config, record)
    parsed = yaml.safe_load(second_config)
    listeners = [
        item for item in parsed["listeners"] if item["name"] == "auto-listener-txt-devtest"
    ]

    assert len(listeners) == 1
    assert listeners[0]["port"] == 7890


def test_clash_adapter_can_use_hysteria2_as_first_hop():
    adapter = ClashVergeAdapter(base_proxy_name="hs2-US")
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
        provider="txt",
    )
    current = """
mixed-port: 7890
proxies:
  - name: hs2-US
    type: hysteria2
    server: 198.51.100.10
    port: 26006
    password: fake-password
    sni: us.example.test
proxy-groups:
  - name: MANUAL
    type: select
    proxies:
      - hs2-US
rules:
  - MATCH,MANUAL
"""

    updated = adapter.merge_config(current, record)
    parsed = yaml.safe_load(updated)
    proxies = {item["name"]: item for item in parsed["proxies"]}

    assert proxies["auto-chain-txt-proxy-b"]["dialer-proxy"] == "hs2-US"
    assert parsed["rules"] == ["MATCH,AUTO-CHAIN"]


def test_clash_adapter_requires_base_proxy_a():
    adapter = ClashVergeAdapter(base_proxy_name="A")
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
    )

    try:
        adapter.merge_config("proxies: []\n", record)
    except ValueError as exc:
        assert "base proxy" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_clash_adapter_removes_temp_file_when_yaml_validation_fails(tmp_path: Path):
    config_path = tmp_path / "clash.yaml"
    original = base_config()
    config_path.write_text(original)
    adapter = ClashVergeAdapter(base_proxy_name="A", config_path=config_path)

    with pytest.raises(yaml.YAMLError):
        adapter._write_config_atomic(":\n")

    assert config_path.read_text() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["clash.yaml", "clash.yaml.bak"]


def test_clash_adapter_writes_backup_and_atomic_config(tmp_path: Path):
    config_path = tmp_path / "clash.yaml"
    config_path.write_text(base_config())
    adapter = ClashVergeAdapter(base_proxy_name="A", config_path=config_path)
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
        provider="txt",
    )

    result = adapter.apply_proxy(record)
    parsed = yaml.safe_load(config_path.read_text())

    assert result.node_name == "auto-chain-txt-proxy-b"
    assert (tmp_path / "clash.yaml.bak").exists()
    assert parsed["proxy-groups"][-1]["name"] == "AUTO-CHAIN"


def test_clash_adapter_reloads_running_config_after_write(tmp_path: Path):
    config_path = tmp_path / "clash.yaml"
    config_path.write_text(base_config(), encoding="utf-8")
    session = FakeSession()
    adapter = ClashVergeAdapter(
        base_proxy_name="A",
        config_path=config_path,
        reload_after_write=True,
        controller_url="http://127.0.0.1:9090",
        controller_secret="secret",
        session=session,
    )
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
        provider="txt",
    )

    result = adapter.apply_proxy(record)

    assert result.reload_status == "reloaded"
    method, url, payload, headers, timeout = session.calls[0]
    assert method == "PUT"
    assert url == "http://127.0.0.1:9090/configs?force=true"
    assert payload == {"path": str(config_path.resolve())}
    assert headers["Authorization"] == "Bearer secret"
    assert timeout == 10.0


def test_clash_adapter_requires_controller_url_when_reload_enabled(tmp_path: Path):
    config_path = tmp_path / "clash.yaml"
    config_path.write_text(base_config(), encoding="utf-8")
    adapter = ClashVergeAdapter(
        base_proxy_name="A",
        config_path=config_path,
        reload_after_write=True,
    )
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
        provider="txt",
    )

    with pytest.raises(ValueError, match="controller_url"):
        adapter.apply_proxy(record)


def test_clash_adapter_returns_listener_metadata(tmp_path: Path):
    config_path = tmp_path / "clash.yaml"
    config_path.write_text(base_config())
    adapter = ClashVergeAdapter(
        base_proxy_name="A",
        config_path=config_path,
        listener_start_port=7890,
    )
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
        provider="txt",
        name="devtest",
    )

    result = adapter.apply_proxy(record)

    assert result.node_name == "auto-chain-txt-devtest"
    assert result.listener_name == "auto-listener-txt-devtest"
    assert result.local_host == "127.0.0.1"
    assert result.local_port == 7890


def test_clash_adapter_writes_current_profile_extension_script(tmp_path: Path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profiles_path = tmp_path / "profiles.yaml"
    script_path = profile_dir / "script-001.js"
    profiles_path.write_text(
        """
current: current-profile
items:
  - uid: current-profile
    type: local
    file: current.yaml
    option:
      script: script-001
""",
        encoding="utf-8",
    )
    script_path.write_text(
        "function main(config, profileName) {\n  return config;\n}\n",
        encoding="utf-8",
    )
    adapter = ClashVergeAdapter(
        base_proxy_name="A",
        write_mode="script",
        profiles_path=profiles_path,
        profile_dir=profile_dir,
        listener_start_port=7891,
    )
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="proxy-b",
        provider="txt",
        name="devtest",
    )

    result = adapter.apply_proxy(record)
    script = script_path.read_text(encoding="utf-8")

    assert result.node_name == "auto-chain-txt-devtest"
    assert result.listener_name == "auto-listener-txt-devtest"
    assert result.local_port == 7891
    assert "AUTOPROXY_MANAGED" in script
    assert '"dialer-proxy": "A"' in script
    assert '"port": 7891' in script
    assert "config.listeners.push(entry.listener);" in script


def test_clash_adapter_script_mode_increments_listener_ports(tmp_path: Path):
    script_path = tmp_path / "Script.js"
    script_path.write_text(
        "function main(config, profileName) {\n  return config;\n}\n",
        encoding="utf-8",
    )
    adapter = ClashVergeAdapter(
        base_proxy_name="A",
        write_mode="script",
        script_path=script_path,
        listener_start_port=7891,
    )
    first = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:5678",
        proxy_id="first",
        provider="txt",
        name="first",
    )
    second = ProxyRecord.from_uri(
        "socks5://5.6.7.8:6789",
        proxy_id="second",
        provider="txt",
        name="second",
    )

    first_result = adapter.apply_proxy(first)
    second_result = adapter.apply_proxy(second)
    script = script_path.read_text(encoding="utf-8")

    assert first_result.local_port == 7891
    assert second_result.local_port == 7892
    assert '"name": "auto-listener-txt-first"' in script
    assert '"name": "auto-listener-txt-second"' in script
    assert '"port": 7891' in script
    assert '"port": 7892' in script


def test_clash_adapter_script_refreshes_existing_entries_to_current_base_proxy(tmp_path: Path):
    script_path = tmp_path / "Script.js"
    adapter = ClashVergeAdapter(
        base_proxy_name="new-hop",
        write_mode="script",
        script_path=script_path,
        listener_start_port=7891,
    )
    stale_script = adapter.render_extension_script(
        [
            {
                "node": {
                    "name": "auto-chain-openbao-old",
                    "type": "socks5",
                    "server": "9.9.9.9",
                    "port": 9999,
                    "dialer-proxy": "old-hop",
                },
                "listener": {
                    "name": "auto-listener-openbao-old",
                    "type": "socks",
                    "listen": "127.0.0.1",
                    "port": 7891,
                    "proxy": "auto-chain-openbao-old",
                },
            }
        ]
    )
    script_path.write_text(stale_script, encoding="utf-8")
    record = ProxyRecord.from_uri(
        "socks5://5.6.7.8:6789",
        proxy_id="second",
        provider="txt",
        name="second",
    )

    adapter.apply_proxy(record)
    script = script_path.read_text(encoding="utf-8")

    assert '"dialer-proxy": "old-hop"' not in script
    assert script.count('"dialer-proxy": "new-hop"') == 2


def test_clash_adapter_script_uses_first_proxy_from_config_path_as_base_proxy(tmp_path: Path):
    script_path = tmp_path / "Script.js"
    script_path.write_text("function main(config, profileName) {\n  return config;\n}\n")
    config_path = tmp_path / "LVBTdzp4LFQd.yaml"
    config_path.write_text(
        """
proxies:
  - name: trojan-US
    type: trojan
    server: example.test
    port: 443
""",
        encoding="utf-8",
    )
    adapter = ClashVergeAdapter(
        base_proxy_name="hs2-US",
        write_mode="script",
        script_path=script_path,
        config_path=config_path,
        listener_start_port=7891,
    )
    record = ProxyRecord.from_uri(
        "socks5://5.6.7.8:6789",
        proxy_id="second",
        provider="txt",
        name="second",
    )

    adapter.apply_proxy(record)
    script = script_path.read_text(encoding="utf-8")

    assert '"dialer-proxy": "trojan-US"' in script
    assert '"dialer-proxy": "hs2-US"' not in script


def test_clash_adapter_finds_config_path_by_name_under_profile_dir(tmp_path: Path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    script_path = tmp_path / "Script.js"
    script_path.write_text("function main(config, profileName) {\n  return config;\n}\n")
    actual_config = profile_dir / "LVBTdzp4LFQd.yaml"
    actual_config.write_text(
        """
proxies:
  - name: trojan-US
    type: trojan
    server: example.test
    port: 443
""",
        encoding="utf-8",
    )
    adapter = ClashVergeAdapter(
        base_proxy_name="hs2-US",
        write_mode="script",
        script_path=script_path,
        config_path=tmp_path / "configs" / "profiles" / "LVBTdzp4LFQd.yaml",
        profile_dir=profile_dir,
        listener_start_port=7891,
    )
    record = ProxyRecord.from_uri(
        "socks5://5.6.7.8:6789",
        proxy_id="second",
        provider="txt",
        name="second",
    )

    adapter.apply_proxy(record)
    script = script_path.read_text(encoding="utf-8")

    assert '"dialer-proxy": "trojan-US"' in script
    assert '"dialer-proxy": "hs2-US"' not in script


def test_clash_adapter_script_refreshes_existing_listeners_to_current_host(tmp_path: Path):
    script_path = tmp_path / "Script.js"
    adapter = ClashVergeAdapter(
        base_proxy_name="new-hop",
        write_mode="script",
        script_path=script_path,
        listener_host="127.0.0.2",
        listener_start_port=7891,
    )
    stale_script = adapter.render_extension_script(
        [
            {
                "node": {
                    "name": "auto-chain-openbao-old",
                    "type": "socks5",
                    "server": "9.9.9.9",
                    "port": 9999,
                    "dialer-proxy": "new-hop",
                },
                "listener": {
                    "name": "auto-listener-openbao-old",
                    "type": "socks",
                    "listen": "127.0.0.1",
                    "port": 7891,
                    "proxy": "auto-chain-openbao-old",
                },
            }
        ]
    )
    script_path.write_text(stale_script, encoding="utf-8")
    record = ProxyRecord.from_uri(
        "socks5://5.6.7.8:6789",
        proxy_id="second",
        provider="txt",
        name="second",
    )

    adapter.apply_proxy(record)
    script = script_path.read_text(encoding="utf-8")

    assert '"listen": "127.0.0.1"' not in script
    assert script.count('"listen": "127.0.0.2"') == 2


def test_clash_adapter_script_removes_stale_yaml_managed_nodes_and_listeners():
    adapter = ClashVergeAdapter(base_proxy_name="A", write_mode="script")

    script = adapter.render_extension_script(
        [
            {
                "node": {"name": "auto-chain-openbao-new"},
                "listener": {"name": "auto-listener-openbao-new", "port": 7891},
            }
        ]
    )

    assert 'startsWith("auto-chain-")' in script
    assert 'startsWith("auto-listener-")' in script
