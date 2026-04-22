from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from requests import HTTPError


@dataclass(slots=True)
class OpenBaoProxySource:
    DEFAULT_SECRET_PATH = "external/proxies"

    base_url: str
    token: str
    mount: str
    read_path: str | None = None
    import_prefix: str | None = None
    secret_path: str | None = None
    ca_cert_path: str | Path | None = None
    timeout: float = 10.0
    now_provider: Any = datetime.now
    session: Any = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        if self.read_path is None:
            self.read_path = self.secret_path or self.DEFAULT_SECRET_PATH
        if self.import_prefix is None:
            self.import_prefix = self.read_path or self.DEFAULT_SECRET_PATH

    def _parent_path(self, path: str) -> str:
        parts = path.strip("/").split("/")
        if len(parts) <= 1:
            return ""
        return "/".join(parts[:-1])

    def _kv_v2_url(self, path: str, *, kind: str = "data") -> str:
        return (
            f"{self.base_url.rstrip('/')}/v1/"
            f"{self.mount.strip('/')}/{kind}/{path.strip('/')}"
        )

    def _request_verify(self) -> bool | str:
        if self.ca_cert_path is None:
            return True
        return str(self.ca_cert_path)

    def _read_secret_data(self, path: str) -> dict[str, Any]:
        response = self.session.get(
            self._kv_v2_url(path),
            headers={"X-Vault-Token": self.token, "Accept": "application/json"},
            timeout=self.timeout,
            verify=self._request_verify(),
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}).get("data")
        if not isinstance(data, dict):
            raise ValueError("OpenBao KV v2 response did not contain data.data")
        return data

    def _read_collection(self, path: str) -> dict[str, dict[str, Any]]:
        try:
            data = self._read_secret_data(path)
        except HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 404:
                return {}
            raise
        proxies = data.get("proxies", data)
        if not isinstance(proxies, dict):
            raise ValueError("OpenBao proxies payload must be an object")
        return {
            str(proxy_id): dict(proxy_data)
            for proxy_id, proxy_data in proxies.items()
            if isinstance(proxy_data, dict)
        }

    def _write_collection(self, path: str, proxies: dict[str, dict[str, Any]]) -> dict[str, Any]:
        response = self.session.post(
            self._kv_v2_url(path),
            json={"data": {"proxies": proxies}},
            headers={
                "X-Vault-Token": self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
            verify=self._request_verify(),
        )
        response.raise_for_status()
        return response.json()

    def _normalize_updated_at(self) -> str:
        timestamp = self.now_provider(UTC) if self.now_provider is datetime.now else self.now_provider()
        if not isinstance(timestamp, datetime):
            raise ValueError("now_provider must return datetime")
        return timestamp.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def fetch_proxy(self) -> dict[str, Any]:
        if self.read_path is None:
            raise ValueError("OpenBao read_path is required for single proxy fetch")
        proxies = self._read_collection(self.read_path)
        if len(proxies) != 1:
            raise ValueError("OpenBao shared proxy secret contains multiple proxies; use --id or --name")
        proxy_id = next(iter(proxies))
        return {
            "id": proxy_id,
            "provider": "openbao",
            **proxies[proxy_id],
        }

    def fetch_proxy_at(self, path: str) -> dict[str, Any]:
        data = self._read_secret_data(path)
        if isinstance(data.get("proxies"), dict):
            raise ValueError("OpenBao shared proxy secret contains multiple proxies; use fetch_proxy_by_id")
        proxy_id = path.rstrip("/").split("/")[-1]
        return {
            "id": proxy_id,
            "provider": "openbao",
            **data,
        }

    def fetch_proxy_by_id(self, proxy_id: str) -> dict[str, Any]:
        assert self.import_prefix is not None
        payload = self._read_collection(self.import_prefix)
        if proxy_id not in payload:
            raise ValueError(f"OpenBao proxy {proxy_id!r} was not found")
        return {
            "id": proxy_id,
            "provider": "openbao",
            **payload[proxy_id],
        }

    def list_proxy_ids(self) -> list[str]:
        assert self.import_prefix is not None
        return sorted(self._read_collection(self.import_prefix).keys())

    def fetch_all_proxies(self) -> list[dict[str, Any]]:
        assert self.import_prefix is not None
        return [
            {
                "id": proxy_id,
                "provider": "openbao",
                **payload,
            }
            for proxy_id, payload in sorted(self._read_collection(self.import_prefix).items())
        ]

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

    def write_proxy(self, proxy_id: str, data: dict[str, Any], *, updated_by: str = "system") -> dict[str, Any]:
        assert self.import_prefix is not None
        clean_data = dict(data)
        clean_data.pop("id", None)
        clean_data["updated_at"] = self._normalize_updated_at()
        clean_data["updated_by"] = updated_by
        secret_path = self.import_prefix.strip("/")
        payload = self._read_collection(secret_path)
        payload[proxy_id] = clean_data
        response_payload = self._write_collection(secret_path, payload)
        return {
            "id": proxy_id,
            "secret_path": secret_path,
            "response": response_payload,
        }

    def write_proxies_from_file(self, path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
        assert self.import_prefix is not None
        secret_path = self.import_prefix.strip("/")
        proxies = self._read_collection(secret_path)
        updated_at = self._normalize_updated_at()
        results = []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError("proxy import JSON must contain objects")
            proxy_id = record.get("id") or record.get("name") or f"proxy-{index:03d}"
            clean_record = dict(record)
            clean_record.pop("id", None)
            clean_record["updated_at"] = updated_at
            clean_record["updated_by"] = "user"
            proxies[str(proxy_id)] = clean_record
            results.append({"id": str(proxy_id), "secret_path": secret_path})
        response_payload = self._write_collection(secret_path, proxies)
        for item in results:
            item["response"] = response_payload
        return results
