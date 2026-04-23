#!/usr/bin/env python3
"""Standalone OpenBao proxy import/query tool.

Examples:
  python3 openbao_tool.py get --config config.openbao.json
  python3 openbao_tool.py get --id proxy-010 --base-url https://127.0.0.1:8200
  python3 openbao_tool.py grep devtest --config config.openbao.json
  python3 openbao_tool.py import --file proxies.json --config config.openbao.json

Environment fallback:
  OPENBAO_BASE_URL / OPENBAO_ADDR, OPENBAO_TOKEN, OPENBAO_PROXY_PATH,
  OPENBAO_CA_CERT_PATH
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests import HTTPError


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATHS = (
    Path("config.local.json"),
    Path("config.openbao.json"),
    SCRIPT_DIR / "config.local.json",
    SCRIPT_DIR / "config.openbao.json",
    Path("config.openbao.example.json"),
    SCRIPT_DIR / "config.openbao.example.json",
)
DEFAULT_SECRET_PATH = "external/proxies"
ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


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
                proxy_id=str(payload["id"]),
                country=payload.get("country"),
                city=payload.get("city"),
                provider=payload.get("provider", "openbao"),
                name=payload.get("name"),
            )
        return cls(
            id=str(payload["id"]),
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OpenBaoProxySource:
    base_url: str
    token: str
    mount: str = "secret"
    read_path: str | None = None
    import_prefix: str | None = None
    ca_cert_path: str | Path | None = None
    timeout: float = 10.0
    now_provider: Any = datetime.now
    session: Any = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        if self.read_path is None:
            self.read_path = self.import_prefix or DEFAULT_SECRET_PATH
        if self.import_prefix is None:
            self.import_prefix = self.read_path or DEFAULT_SECRET_PATH

    def _kv_v2_url(self, path: str, *, kind: str = "data") -> str:
        return (
            f"{self.base_url.rstrip('/')}/v1/"
            f"{self.mount.strip('/')}/{kind}/{path.strip('/')}"
        )

    def _request_verify(self) -> bool | str:
        if not self.ca_cert_path:
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

    def fetch_proxy_by_id(self, proxy_id: str) -> dict[str, Any]:
        assert self.import_prefix is not None
        payload = self._read_collection(self.import_prefix)
        if proxy_id not in payload:
            raise ValueError(f"OpenBao proxy {proxy_id!r} was not found")
        return {"id": proxy_id, "provider": "openbao", **payload[proxy_id]}

    def fetch_all_proxies(self) -> list[dict[str, Any]]:
        assert self.import_prefix is not None
        return [
            {"id": proxy_id, "provider": "openbao", **payload}
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

    def write_proxies_from_file(self, path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
        assert self.import_prefix is not None
        secret_path = self.import_prefix.strip("/")
        proxies = self._read_collection(secret_path)
        updated_at = self._normalize_updated_at()
        results: list[dict[str, Any]] = []
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


def load_dotenv(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            env_name = match.group(1)
            default = match.group(2)
            if env_name not in os.environ:
                if default is not None:
                    return default
                raise ValueError(f"required environment variable {env_name!r} is not set")
            return os.environ[env_name]

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: resolve_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_env(item) for item in value]
    return value


def resolve_config_path(path: str | None) -> Path | None:
    if path:
        return Path(path).expanduser().resolve()
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate.resolve()
    return None


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    load_dotenv(path.parent / ".env")
    config = resolve_env(json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(config, dict):
        raise ValueError("config JSON must be an object")
    return config


def build_source(args: argparse.Namespace) -> OpenBaoProxySource:
    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    source_config = dict(config.get("proxy_source", config.get("openbao", {})))

    base_url = args.base_url or source_config.get("base_url") or os.environ.get("OPENBAO_BASE_URL") or os.environ.get("OPENBAO_ADDR")
    token = args.token or source_config.get("token") or os.environ.get("OPENBAO_TOKEN")
    if not base_url:
        raise ValueError("OpenBao base URL is required; use --base-url, config proxy_source.base_url, or OPENBAO_BASE_URL")
    if not token:
        raise ValueError("OpenBao token is required; use --token, config proxy_source.token, or OPENBAO_TOKEN")

    proxy_path = (
        args.path
        or source_config.get("import_prefix")
        or source_config.get("read_path")
        or source_config.get("secret_path")
        or os.environ.get("OPENBAO_PROXY_PATH")
        or DEFAULT_SECRET_PATH
    )
    ca_cert_path = args.ca_cert_path or source_config.get("ca_cert_path") or os.environ.get("OPENBAO_CA_CERT_PATH")
    return OpenBaoProxySource(
        base_url=base_url,
        token=token,
        mount=args.mount or source_config.get("mount", "secret"),
        read_path=proxy_path,
        import_prefix=proxy_path,
        ca_cert_path=ca_cert_path or None,
        timeout=float(args.timeout or source_config.get("timeout", 10.0)),
    )


def normalize_for_output(payload: dict[str, Any]) -> dict[str, Any]:
    return ProxyRecord.from_mapping(payload).to_dict()


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_get(args: argparse.Namespace) -> int:
    source = build_source(args)
    if args.id:
        print_json(normalize_for_output(source.fetch_proxy_by_id(args.id)))
        return 0
    if args.name:
        print_json([normalize_for_output(item) for item in source.find_proxies_by_name(args.name)])
        return 0
    print_json([normalize_for_output(item) for item in source.fetch_all_proxies()])
    return 0


def cmd_grep(args: argparse.Namespace) -> int:
    source = build_source(args)
    print_json([normalize_for_output(item) for item in source.grep_proxies(args.keyword)])
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    source = build_source(args)
    print_json({"written": source.write_proxies_from_file(Path(args.file).expanduser())})
    return 0


def add_common_openbao_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to config JSON. Defaults to config.local.json/config.openbao.json when present.")
    parser.add_argument("--base-url", help="OpenBao base URL, e.g. https://127.0.0.1:8200.")
    parser.add_argument("--token", help="OpenBao token. Prefer OPENBAO_TOKEN or config for shared usage.")
    parser.add_argument("--mount", help="KV v2 mount name. Defaults to secret.")
    parser.add_argument("--path", help=f"KV v2 secret path. Defaults to {DEFAULT_SECRET_PATH}.")
    parser.add_argument("--ca-cert-path", help="Optional CA certificate bundle path for self-signed HTTPS.")
    parser.add_argument("--timeout", type=float, help="HTTP timeout in seconds. Defaults to 10.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone OpenBao proxy import/query tool.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    get_parser = subcommands.add_parser("get", aliases=["openbao-get"], help="List proxies or read by id/name.")
    add_common_openbao_args(get_parser)
    get_group = get_parser.add_mutually_exclusive_group()
    get_group.add_argument("--id", help="Read one proxy by id.")
    get_group.add_argument("--name", help="Read proxies whose name matches exactly.")
    get_parser.set_defaults(handler=cmd_get)

    grep_parser = subcommands.add_parser("grep", aliases=["openbao-grep"], help="Search all proxy fields.")
    add_common_openbao_args(grep_parser)
    grep_parser.add_argument("keyword", help="Case-insensitive keyword.")
    grep_parser.set_defaults(handler=cmd_grep)

    import_parser = subcommands.add_parser("import", aliases=["openbao-import"], help="Import proxy JSON into OpenBao.")
    add_common_openbao_args(import_parser)
    import_parser.add_argument("--file", required=True, help="Path to a proxy JSON object or array.")
    import_parser.set_defaults(handler=cmd_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
