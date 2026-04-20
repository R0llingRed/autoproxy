from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autoproxy.models import ProxyRecord


DEFAULT_START_URL = "https://www.browserscan.net"


@dataclass(slots=True)
class CamoufoxLaunchResult:
    browser: str
    proxy_id: str
    proxy_name: str | None
    profile_dir: str
    local_host: str
    local_port: int
    proxy_server: str
    start_url: str
    template_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CamoufoxAdapter:
    profiles_dir: Path
    templates_dir: Path
    bindings_path: Path
    headless: bool | None = None
    geoip: bool | None = None
    humanize: bool | None = None
    start_url: str | None = None
    timeout: float = 30.0
    os: list[str] | str | None = None
    locale: str | None = None
    block_images: bool | None = None
    camoufox_factory: Any | None = None

    def launch_with_local_proxy(
        self,
        record: ProxyRecord,
        *,
        local_host: str,
        local_port: int,
        template_name: str | None = None,
        start_url: str | None = None,
        keep_open: bool = True,
    ) -> CamoufoxLaunchResult:
        template = self.get_template(template_name) if template_name else {}
        launch_options = self._launch_options(template, start_url=start_url)
        profile_dir = self.profiles_dir / record.id
        profile_dir.mkdir(parents=True, exist_ok=True)
        proxy_server = f"socks5://{local_host}:{local_port}"
        result = CamoufoxLaunchResult(
            browser="camoufox",
            proxy_id=record.id,
            proxy_name=record.name,
            profile_dir=str(profile_dir),
            local_host=local_host,
            local_port=local_port,
            proxy_server=proxy_server,
            start_url=launch_options.pop("start_url"),
            template_name=template_name,
        )
        self._upsert_binding(result)
        factory = self.camoufox_factory or self._load_camoufox_factory()
        camoufox_kwargs = {
            **launch_options,
            "proxy": {"server": proxy_server},
            "persistent_context": True,
            "user_data_dir": str(profile_dir),
        }
        with factory(**camoufox_kwargs) as browser:
            page = browser.new_page()
            page.goto(result.start_url, timeout=int(self.timeout * 1000))
            if keep_open:
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
        return result

    def list_templates(self) -> list[dict[str, Any]]:
        if not self.templates_dir.exists():
            return []
        templates = [self._read_template(path) for path in sorted(self.templates_dir.glob("*.json"))]
        return templates

    def get_template(self, name: str) -> dict[str, Any]:
        path = self.templates_dir / f"{name}.json"
        if not path.exists():
            raise ValueError(f"Camoufox template {name!r} not found in {self.templates_dir}")
        template = self._read_template(path)
        if template.get("name", name) != name:
            raise ValueError(f"Camoufox template name mismatch in {path}")
        return template

    def list_bindings(self) -> list[dict[str, Any]]:
        return list(self._read_bindings().values())

    def get_binding(self, proxy_id: str) -> dict[str, Any] | None:
        return self._read_bindings().get(proxy_id)

    def _launch_options(
        self,
        template: dict[str, Any],
        *,
        start_url: str | None,
    ) -> dict[str, Any]:
        options = {
            "headless": False,
            "geoip": True,
            "humanize": True,
            "start_url": DEFAULT_START_URL,
        }
        options.update(template)
        options.pop("name", None)
        configured = {
            "headless": self.headless,
            "geoip": self.geoip,
            "humanize": self.humanize,
            "start_url": self.start_url,
            "os": self.os,
            "locale": self.locale,
            "block_images": self.block_images,
        }
        for key, value in configured.items():
            if value is not None:
                options[key] = value
        if start_url:
            options["start_url"] = start_url
        options.setdefault("start_url", DEFAULT_START_URL)
        return options

    def _upsert_binding(self, result: CamoufoxLaunchResult) -> None:
        bindings = self._read_bindings()
        bindings[result.proxy_id] = {
            **result.to_dict(),
            "last_launched_at": datetime.now(UTC).isoformat(),
        }
        self.bindings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.bindings_path.with_suffix(f"{self.bindings_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(bindings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(self.bindings_path)

    def _read_bindings(self) -> dict[str, dict[str, Any]]:
        if not self.bindings_path.exists():
            return {}
        try:
            payload = json.loads(self.bindings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Camoufox bindings JSON: {self.bindings_path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Camoufox bindings must be a JSON object: {self.bindings_path}")
        return dict(payload)

    def _read_template(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Camoufox template JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Camoufox template must be a JSON object: {path}")
        if "name" not in payload:
            payload["name"] = path.stem
        return payload

    def _load_camoufox_factory(self):
        try:
            from camoufox.sync_api import Camoufox
        except ImportError as exc:
            raise ValueError(
                "Camoufox is not installed. Install it with "
                'python3 -m pip install -e ".[camoufox]" and run '
                "python3 -m camoufox fetch."
            ) from exc
        return Camoufox
