from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoproxy.models import ProxyRecord, RunArtifacts, ValidationResult
from autoproxy.reporter import Reporter


@dataclass(slots=True)
class FlowRunner:
    proxy_source: Any
    sub2api: Any
    clash: Any
    report_base_dir: Path
    adspower: Any | None = None

    def run(self, *, session_tag: str) -> RunArtifacts:
        proxy_payload = self.proxy_source.fetch_proxy()
        proxy = ProxyRecord.from_mapping(proxy_payload)
        sub2api_proxy_id = self.sub2api.sync_proxy(proxy)
        clash_result = self.clash.apply_proxy(proxy)
        adspower_proxy_id = ""
        adspower_profile_id = ""
        if self.adspower is not None:
            adspower_proxy_id = self.adspower.add_proxy(proxy)
            adspower_profile_id = self.adspower.create_profile_with_local_proxy(
                proxy,
                local_host=clash_result.local_host,
                local_port=clash_result.local_port,
            )
        validation = ValidationResult(
            status="SKIPPED",
            stage="browser_validation_not_run",
            reasons=["adspower_profile_created_without_browser_start"],
            checks={
                "local_proxy_host": clash_result.local_host,
                "local_proxy_port": clash_result.local_port,
                "clash_reload_status": getattr(clash_result, "reload_status", "skipped"),
                "adspower_profile_id": adspower_profile_id,
            },
        )
        artifacts = RunArtifacts(
            session_tag=session_tag,
            proxy=proxy,
            sub2api_proxy_id=sub2api_proxy_id,
            clash_node_name=clash_result.node_name,
            validation=validation,
            screenshots=[],
            adspower_proxy_id=adspower_proxy_id,
            adspower_profile_id=adspower_profile_id,
        )
        Reporter(base_dir=self.report_base_dir).write_run_report(artifacts)
        return artifacts
