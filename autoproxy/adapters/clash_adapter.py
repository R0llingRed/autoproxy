from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from autoproxy.models import ProxyRecord


@dataclass(slots=True)
class ClashApplyResult:
    node_name: str
    listener_name: str
    local_host: str
    local_port: int


@dataclass(slots=True)
class ClashVergeAdapter:
    base_proxy_name: str = "A"
    config_path: Path | None = None
    managed_group_name: str = "AUTO-CHAIN"
    managed_proxy_prefix: str = "auto-chain-"
    managed_listener_prefix: str = "auto-listener-"
    listener_start_port: int = 7890
    listener_host: str = "127.0.0.1"

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
        return self.listener_for_record(updated, record)

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
