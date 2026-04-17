from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from autoproxy.models import ProxyRecord


@dataclass(slots=True)
class AdsPowerAdapter:
    base_url: str
    api_key: str
    timeout: float = 10.0
    session: Any = requests

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def add_proxy(self, record: ProxyRecord) -> str:
        existing = self.find_proxy(record)
        if existing:
            return existing
        payload = [
            {
                "type": record.type,
                "host": record.host,
                "port": str(record.port),
                "user": record.username or "",
                "password": record.password or "",
                "remark": record.name or record.id,
            }
        ]
        response = self.session.post(
            f"{self.base_url.rstrip('/')}/api/v2/proxy-list/create",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = self._json_response(response)
        proxy_ids = data.get("data", {}).get("proxy_id") or []
        if not proxy_ids:
            raise ValueError(f"AdsPower did not return a proxy_id: {data}")
        return str(proxy_ids[0])

    def find_proxy(self, record: ProxyRecord) -> str | None:
        response = self.session.post(
            f"{self.base_url.rstrip('/')}/api/v2/proxy-list/list",
            json={"page": "1", "limit": "200"},
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = self._json_response(response)
        for item in data.get("data", {}).get("list", []):
            if (
                item.get("type") == record.type
                and item.get("host") == record.host
                and str(item.get("port")) == str(record.port)
                and (item.get("user") or "") == (record.username or "")
            ):
                return str(item["proxy_id"])
        return None

    def create_profile_with_local_proxy(
        self,
        record: ProxyRecord,
        *,
        local_host: str,
        local_port: int,
        group_id: str = "0",
    ) -> str:
        existing = self.find_profile(record, local_host=local_host, local_port=local_port)
        if existing:
            return existing
        payload = {
            "name": record.name or record.id,
            "group_id": str(group_id),
            "user_proxy_config": {
                "proxy_soft": "other",
                "proxy_type": "socks5",
                "proxy_host": local_host,
                "proxy_port": str(local_port),
            },
        }
        response = self.session.post(
            f"{self.base_url.rstrip('/')}/api/v1/user/create",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = self._json_response(response)
        profile_id = (
            data.get("data", {}).get("id")
            or data.get("data", {}).get("user_id")
            or data.get("data", {}).get("profile_id")
        )
        if not profile_id:
            raise ValueError(f"AdsPower did not return a profile id: {data}")
        return str(profile_id)

    def find_profile(
        self,
        record: ProxyRecord,
        *,
        local_host: str,
        local_port: int,
    ) -> str | None:
        response = self.session.get(
            f"{self.base_url.rstrip('/')}/api/v1/user/list",
            params={"page": 1, "page_size": 200},
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = self._json_response(response)
        expected_name = record.name or record.id
        for item in data.get("data", {}).get("list", []):
            proxy_config = item.get("user_proxy_config") or {}
            if (
                item.get("name") == expected_name
                and proxy_config.get("proxy_host") == local_host
                and str(proxy_config.get("proxy_port")) == str(local_port)
            ):
                return str(item.get("user_id") or item.get("id") or item.get("profile_id"))
        return None

    def _json_response(self, response: Any) -> dict[str, Any]:
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise ValueError(f"AdsPower API failed: {data}")
        return data
