from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests


@dataclass(slots=True)
class OpenBaoProxySource:
    base_url: str
    token: str
    mount: str
    secret_path: str
    timeout: float = 10.0
    session: Any = field(default_factory=requests.Session)

    @property
    def proxy_prefix(self) -> str:
        parts = self.secret_path.strip("/").split("/")
        if len(parts) <= 1:
            return ""
        return "/".join(parts[:-1])

    def fetch_proxy(self) -> dict[str, Any]:
        url = (
            f"{self.base_url.rstrip('/')}/v1/"
            f"{self.mount.strip('/')}/data/{self.secret_path.strip('/')}"
        )
        response = self.session.get(
            url,
            headers={"X-Vault-Token": self.token, "Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}).get("data")
        if not isinstance(data, dict):
            raise ValueError("OpenBao KV v2 response did not contain data.data")
        proxy_id = self.secret_path.rstrip("/").split("/")[-1]
        return {
            "id": proxy_id,
            "provider": "openbao",
            **data,
        }

    def write_proxy(self, proxy_id: str, data: dict[str, Any]) -> dict[str, Any]:
        clean_data = dict(data)
        clean_data.pop("id", None)
        secret_path = f"{self.proxy_prefix}/{proxy_id}".strip("/")
        url = (
            f"{self.base_url.rstrip('/')}/v1/"
            f"{self.mount.strip('/')}/data/{secret_path}"
        )
        response = self.session.post(
            url,
            json={"data": clean_data},
            headers={
                "X-Vault-Token": self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return {
            "id": proxy_id,
            "secret_path": secret_path,
            "response": response.json(),
        }

    def write_proxies_from_file(self, path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text())
        records = payload if isinstance(payload, list) else [payload]
        results = []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError("proxy import JSON must contain objects")
            proxy_id = record.get("id") or record.get("name") or f"proxy-{index:03d}"
            results.append(self.write_proxy(str(proxy_id), record))
        return results
