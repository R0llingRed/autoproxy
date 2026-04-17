from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from autoproxy.models import ProxyRecord


@dataclass(slots=True)
class Sub2ApiAdapter:
    base_url: str
    token: str | None = None
    email: str | None = None
    password: str | None = None
    login_path: str = "/api/v1/auth/login"
    list_path: str = "/api/v1/admin/proxies"
    create_path: str = "/api/admin/proxies"
    timezone: str = "Asia/Shanghai"
    timeout: float = 10.0
    session: Any = requests

    def natural_key(self, record: ProxyRecord) -> str:
        return f"{record.type}|{record.host}|{record.port}|{record.username or ''}"

    def build_login_payload(self) -> dict[str, str]:
        if not self.email or not self.password:
            raise ValueError("sub2api email and password are required for login")
        return {"email": self.email, "password": self.password}

    def build_proxy_list_params(self) -> dict[str, Any]:
        return {
            "page": 1,
            "page_size": 20,
            "status": "",
            "timezone": self.timezone,
        }

    def build_proxy_payload(self, record: ProxyRecord) -> dict[str, Any]:
        remark = "/".join(part for part in [record.country, record.city] if part)
        return {
            "name": record.node_name,
            "protocol": record.type,
            "host": record.host,
            "port": record.port,
            "username": record.username or "",
            "password": record.password or "",
            "status": 1,
            "remark": remark,
        }

    def _build_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def login(self) -> str:
        if self.token:
            return self.token
        response = self.session.post(
            f"{self.base_url.rstrip('/')}{self.login_path}",
            json=self.build_login_payload(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("data", {}).get("access_token")
        if not token:
            raise ValueError("sub2api login did not return an access token")
        self.token = token
        return token

    def list_proxies(self) -> dict[str, Any]:
        self.login()
        response = self.session.get(
            f"{self.base_url.rstrip('/')}{self.list_path}",
            params=self.build_proxy_list_params(),
            headers=self._build_headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def sync_proxy(self, record: ProxyRecord) -> str:
        self.login()
        existing = self.find_proxy(record)
        if existing:
            return existing
        payload = self.build_proxy_payload(record)
        response = self.session.post(
            f"{self.base_url.rstrip('/')}{self.create_path}",
            json=payload,
            headers=self._build_headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        proxy_id = data.get("id") or data.get("data", {}).get("id")
        if not proxy_id:
            raise ValueError("sub2api did not return a proxy id")
        return str(proxy_id)

    def find_proxy(self, record: ProxyRecord) -> str | None:
        data = self.list_proxies()
        for item in data.get("data", {}).get("items", []):
            if (
                item.get("protocol") == record.type
                and item.get("host") == record.host
                and str(item.get("port")) == str(record.port)
                and (item.get("username") or "") == (record.username or "")
            ):
                return str(item["id"])
        return None
