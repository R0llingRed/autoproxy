from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from requests import HTTPError


@dataclass(slots=True)
class OpenBaoProxySource:
    base_url: str
    token: str
    mount: str
    read_path: str | None = None
    import_prefix: str | None = None
    secret_path: str | None = None
    timeout: float = 10.0
    session: Any = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        if self.read_path is None:
            self.read_path = self.secret_path
        if self.import_prefix is None:
            if self.read_path is None:
                raise ValueError("OpenBao import_prefix is required when read_path is not set")
            self.import_prefix = self._parent_path(self.read_path)

    def _parent_path(self, path: str) -> str:
        parts = path.strip("/").split("/")
        if len(parts) <= 1:
            return ""
        return "/".join(parts[:-1])

    def fetch_proxy(self) -> dict[str, Any]:
        if self.read_path is None:
            raise ValueError("OpenBao read_path is required for single proxy fetch")
        return self.fetch_proxy_at(self.read_path)

    def fetch_proxy_at(self, path: str) -> dict[str, Any]:
        url = (
            f"{self.base_url.rstrip('/')}/v1/"
            f"{self.mount.strip('/')}/data/{path.strip('/')}"
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
        proxy_id = path.rstrip("/").split("/")[-1]
        return {
            "id": proxy_id,
            "provider": "openbao",
            **data,
        }

    def fetch_proxy_by_id(self, proxy_id: str) -> dict[str, Any]:
        assert self.import_prefix is not None
        return self.fetch_proxy_at(f"{self.import_prefix.strip('/')}/{proxy_id}")

    def list_proxy_ids(self) -> list[str]:
        assert self.import_prefix is not None
        url = (
            f"{self.base_url.rstrip('/')}/v1/"
            f"{self.mount.strip('/')}/metadata/{self.import_prefix.strip('/')}"
        )
        response = self.session.request(
            "LIST",
            url,
            headers={"X-Vault-Token": self.token, "Accept": "application/json"},
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 404:
                return []
            raise
        keys = response.json().get("data", {}).get("keys", [])
        return [str(key) for key in keys if not str(key).endswith("/")]

    def fetch_all_proxies(self) -> list[dict[str, Any]]:
        return [self.fetch_proxy_by_id(proxy_id) for proxy_id in self.list_proxy_ids()]

    def find_proxies_by_name(self, name: str) -> list[dict[str, Any]]:
        return [item for item in self.fetch_all_proxies() if item.get("name") == name]

    def grep_proxies(self, keyword: str) -> list[dict[str, Any]]:
        normalized_keyword = keyword.casefold()
        return [
            item
            for item in self.fetch_all_proxies()
            if self._contains_text(item, normalized_keyword)
        ]

    def _contains_text(self, value: Any, normalized_keyword: str) -> bool:
        if isinstance(value, dict):
            return any(
                self._contains_text(key, normalized_keyword)
                or self._contains_text(item, normalized_keyword)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(self._contains_text(item, normalized_keyword) for item in value)
        return normalized_keyword in str(value).casefold()

    def write_proxy(self, proxy_id: str, data: dict[str, Any]) -> dict[str, Any]:
        assert self.import_prefix is not None
        clean_data = dict(data)
        clean_data.pop("id", None)
        secret_path = f"{self.import_prefix.strip('/')}/{proxy_id}".strip("/")
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
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
        results = []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError("proxy import JSON must contain objects")
            proxy_id = record.get("id") or record.get("name") or f"proxy-{index:03d}"
            results.append(self.write_proxy(str(proxy_id), record))
        return results
