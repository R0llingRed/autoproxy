from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import requests
import yaml

from autoproxy.models import ProxyRecord


@dataclass(slots=True)
class ClashApplyResult:
    node_name: str
    listener_name: str
    local_host: str
    local_port: int
    reload_status: str = "skipped"


@dataclass(slots=True)
class ClashVergeAdapter:
    base_proxy_name: str = "A"
    config_path: Path | None = None
    write_mode: str = "yaml"
    script_path: Path | None = None
    profiles_path: Path | None = None
    profile_dir: Path | None = None
    managed_group_name: str = "AUTO-CHAIN"
    managed_proxy_prefix: str = "auto-chain-"
    managed_listener_prefix: str = "auto-listener-"
    listener_start_port: int = 7890
    listener_host: str = "127.0.0.1"
    reload_after_write: bool = False
    controller_url: str | None = None
    controller_secret: str | None = None
    reload_force: bool = True
    timeout: float = 10.0
    session: Any = field(default_factory=requests.Session)

    def chain_node_name(self, record: ProxyRecord) -> str:
        return f"{self.managed_proxy_prefix}{record.node_name}"

    def listener_name(self, record: ProxyRecord) -> str:
        return f"{self.managed_listener_prefix}{record.node_name}"

    def build_chained_proxy_node(self, record: ProxyRecord) -> dict[str, Any]:
        node: dict[str, Any] = {
            "name": self.chain_node_name(record),
            "type": record.type,
            "server": record.host,
            "port": record.port,
            "dialer-proxy": self.base_proxy_name,
        }
        if record.username:
            node["username"] = record.username
        if record.password:
            node["password"] = record.password
        return node

    def merge_config(self, current_config: str, record: ProxyRecord) -> str:
        config = yaml.safe_load(current_config) or {}
        proxies = list(config.get("proxies") or [])
        if not any(item.get("name") == self.base_proxy_name for item in proxies):
            raise ValueError(f"Base proxy {self.base_proxy_name!r} was not found")

        chain_node = self.build_chained_proxy_node(record)
        proxies = [item for item in proxies if item.get("name") != chain_node["name"]]
        proxies.append(chain_node)
        config["proxies"] = proxies
        managed_proxy_names = [
            item["name"]
            for item in proxies
            if str(item.get("name", "")).startswith(self.managed_proxy_prefix)
        ]

        groups = [
            item
            for item in list(config.get("proxy-groups") or [])
            if item.get("name") != self.managed_group_name
        ]
        groups.append(
            {
                "name": self.managed_group_name,
                "type": "select",
                "proxies": managed_proxy_names,
            }
        )
        config["proxy-groups"] = groups
        config["listeners"] = self._merge_listeners(config.get("listeners"), record, chain_node["name"])
        config["rules"] = self._merge_rules(config.get("rules"))

        return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)

    def _merge_listeners(
        self,
        current_listeners: Any,
        record: ProxyRecord,
        chain_node_name: str,
    ) -> list[dict[str, Any]]:
        listeners = list(current_listeners or [])
        name = self.listener_name(record)
        existing = next((item for item in listeners if item.get("name") == name), None)
        used_ports = {int(item["port"]) for item in listeners if "port" in item}
        if existing:
            port = int(existing["port"])
            listeners = [item for item in listeners if item.get("name") != name]
        else:
            port = self._next_listener_port(used_ports)
        listeners.append(
            {
                "name": name,
                "type": "socks",
                "listen": self.listener_host,
                "port": port,
                "proxy": chain_node_name,
            }
        )
        return listeners

    def _next_listener_port(self, used_ports: set[int]) -> int:
        port = self.listener_start_port
        while port in used_ports:
            port += 1
        return port

    def _merge_rules(self, current_rules: Any) -> list[str]:
        rules = [rule for rule in list(current_rules or []) if not str(rule).startswith("MATCH,")]
        rules.append(f"MATCH,{self.managed_group_name}")
        return rules

    def listener_for_record(self, current_config: str, record: ProxyRecord) -> ClashApplyResult:
        config = yaml.safe_load(current_config) or {}
        name = self.listener_name(record)
        for item in config.get("listeners") or []:
            if item.get("name") == name:
                return ClashApplyResult(
                    node_name=self.chain_node_name(record),
                    listener_name=name,
                    local_host=str(item.get("listen", self.listener_host)),
                    local_port=int(item["port"]),
                )
        raise ValueError(f"Listener {name!r} was not found after config merge")

    def apply_proxy(self, record: ProxyRecord) -> ClashApplyResult:
        if self.write_mode == "script":
            return self.apply_proxy_script(record)
        if self.write_mode != "yaml":
            raise ValueError(f"unsupported Clash write_mode: {self.write_mode}")
        node_name = self.chain_node_name(record)
        if self.config_path is None:
            return ClashApplyResult(
                node_name=node_name,
                listener_name=self.listener_name(record),
                local_host=self.listener_host,
                local_port=self.listener_start_port,
            )
        current = self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
        updated = self.merge_config(current, record)
        self._write_config_atomic(updated)
        result = self.listener_for_record(updated, record)
        if self.reload_after_write:
            self.reload_config()
            result.reload_status = "reloaded"
        return result

    def apply_proxy_script(self, record: ProxyRecord) -> ClashApplyResult:
        script_path = self.resolve_script_path()
        current_script = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
        entries = self._managed_entries_from_script(current_script)
        node = self.build_chained_proxy_node(record)
        listener_name = self.listener_name(record)
        existing = next(
            (entry for entry in entries if entry.get("listener", {}).get("name") == listener_name),
            None,
        )
        if existing:
            port = int(existing["listener"]["port"])
        else:
            used_ports = {
                int(entry["listener"]["port"])
                for entry in entries
                if isinstance(entry.get("listener"), dict) and "port" in entry["listener"]
            }
            port = self._next_listener_port(used_ports)
        listener = {
            "name": listener_name,
            "type": "socks",
            "listen": self.listener_host,
            "port": port,
            "proxy": node["name"],
        }
        entries = [
            entry
            for entry in entries
            if entry.get("node", {}).get("name") != node["name"]
            and entry.get("listener", {}).get("name") != listener_name
        ]
        entries.append({"node": node, "listener": listener})
        script_path.parent.mkdir(parents=True, exist_ok=True)
        if script_path.exists():
            shutil.copy2(script_path, script_path.with_suffix(script_path.suffix + ".bak"))
        script_path.write_text(self.render_extension_script(entries), encoding="utf-8")
        return ClashApplyResult(
            node_name=node["name"],
            listener_name=listener_name,
            local_host=self.listener_host,
            local_port=port,
        )

    def resolve_script_path(self) -> Path:
        if self.script_path is not None:
            return self.script_path
        if self.profiles_path is None:
            raise ValueError("script_path or profiles_path is required for script write_mode")
        profile_dir = self.profile_dir or self.profiles_path.parent / "profiles"
        profiles = yaml.safe_load(self.profiles_path.read_text(encoding="utf-8")) or {}
        current = profiles.get("current")
        for item in profiles.get("items") or []:
            if item.get("uid") != current:
                continue
            script_uid = (item.get("option") or {}).get("script")
            if not script_uid:
                raise ValueError(f"current Clash profile {current!r} does not define option.script")
            return profile_dir / f"{script_uid}.js"
        raise ValueError(f"current Clash profile {current!r} was not found in profiles.yaml")

    def _managed_entries_from_script(self, script: str) -> list[dict[str, Any]]:
        start = script.find("const AUTOPROXY_MANAGED = ")
        if start < 0:
            return []
        start += len("const AUTOPROXY_MANAGED = ")
        end = script.find(";\n", start)
        if end < 0:
            return []
        payload = json.loads(script[start:end])
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def render_extension_script(self, entries: list[dict[str, Any]]) -> str:
        payload = json.dumps(entries, ensure_ascii=False, indent=2)
        return f"""// Generated by AutoProxy. Edit through AutoProxy, not manually.
const AUTOPROXY_MANAGED = {payload};

function main(config, profileName) {{
  config.proxies = config.proxies || [];
  config["proxy-groups"] = config["proxy-groups"] || [];
  config.rules = config.rules || [];
  config.listeners = config.listeners || [];

  const managedNodeNames = AUTOPROXY_MANAGED.map((entry) => entry.node.name);
  config.proxies = config.proxies.filter((item) => !String(item.name || "").startsWith("{self.managed_proxy_prefix}"));
  for (const entry of AUTOPROXY_MANAGED) {{
    config.proxies.push(entry.node);
  }}

  config["proxy-groups"] = config["proxy-groups"].filter((item) => item.name !== "{self.managed_group_name}");
  config["proxy-groups"].push({{
    name: "{self.managed_group_name}",
    type: "select",
    proxies: managedNodeNames
  }});

  const managedListenerNames = AUTOPROXY_MANAGED.map((entry) => entry.listener.name);
  config.listeners = config.listeners.filter((item) => !String(item.name || "").startsWith("{self.managed_listener_prefix}"));
  for (const entry of AUTOPROXY_MANAGED) {{
    config.listeners.push(entry.listener);
  }}

  config.rules = config.rules.filter((rule) => !String(rule).startsWith("MATCH,"));
  config.rules.push("MATCH,{self.managed_group_name}");

  return config;
}}
"""

    def reload_config(self) -> None:
        if self.config_path is None:
            raise ValueError("config_path is required for Clash reload")
        if not self.controller_url:
            raise ValueError("clash controller_url is required when reload_after_write is enabled")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.controller_secret:
            headers["Authorization"] = f"Bearer {self.controller_secret}"
        url = f"{self.controller_url.rstrip('/')}/configs"
        if self.reload_force:
            url = f"{url}?force=true"
        response = self.session.put(
            url,
            json={"path": str(self.config_path.resolve())},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

    def _write_config_atomic(self, content: str) -> None:
        assert self.config_path is not None
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            shutil.copy2(self.config_path, self.config_path.with_suffix(self.config_path.suffix + ".bak"))
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.config_path.parent,
            delete=False,
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        try:
            yaml.safe_load(temp_path.read_text(encoding="utf-8"))
            os.replace(temp_path, self.config_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
