from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True)
class ProxyRecord:
    id: str
    name: str | None
    type: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    country: str | None = None
    city: str | None = None
    provider: str = "openbao"
    raw_uri: str | None = None

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        proxy_id: str,
        country: str | None = None,
        city: str | None = None,
        provider: str = "openbao",
        name: str | None = None,
    ) -> "ProxyRecord":
        parsed = urlparse(uri)
        if not parsed.scheme:
            raise ValueError("proxy URI must include a scheme")
        if parsed.port is None:
            raise ValueError("proxy URI must include a port")
        if not parsed.hostname:
            raise ValueError("proxy URI must include a host")
        return cls(
            id=proxy_id,
            name=name,
            type=parsed.scheme,
            host=parsed.hostname,
            port=parsed.port,
            username=parsed.username,
            password=parsed.password,
            country=country,
            city=city,
            provider=provider,
            raw_uri=uri,
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ProxyRecord":
        raw_uri = payload.get("raw_uri")
        if raw_uri:
            return cls.from_uri(
                raw_uri,
                proxy_id=payload["id"],
                country=payload.get("country"),
                city=payload.get("city"),
                provider=payload.get("provider", "openbao"),
                name=payload.get("name"),
            )
        return cls(
            id=payload["id"],
            name=payload.get("name"),
            type=payload["type"],
            host=payload["host"],
            port=int(payload["port"]),
            username=payload.get("username"),
            password=payload.get("password"),
            country=payload.get("country"),
            city=payload.get("city"),
            provider=payload.get("provider", "openbao"),
            raw_uri=payload.get("raw_uri"),
        )

    @property
    def node_name(self) -> str:
        return f"{self.provider}-{self.name or self.id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidationResult:
    status: str
    stage: str
    reasons: list[str]
    checks: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ValidationResult":
        return cls(
            status=payload["status"],
            stage=payload["stage"],
            reasons=list(payload.get("reasons", [])),
            checks=dict(payload.get("checks", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stage": self.stage,
            "reasons": self.reasons,
            "checks": self.checks,
        }


@dataclass(slots=True)
class RunArtifacts:
    session_tag: str
    proxy: ProxyRecord
    sub2api_proxy_id: str
    clash_node_name: str
    validation: ValidationResult
    screenshots: list[str] = field(default_factory=list)
    adspower_proxy_id: str = ""
    adspower_profile_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_tag": self.session_tag,
            "proxy": self.proxy.to_dict(),
            "sub2api_proxy_id": self.sub2api_proxy_id,
            "clash_node_name": self.clash_node_name,
            "validation": self.validation.to_dict(),
            "screenshots": self.screenshots,
            "adspower_proxy_id": self.adspower_proxy_id,
            "adspower_profile_id": self.adspower_profile_id,
        }
