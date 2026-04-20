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
    browser_adapter: Any | None = None

    def run(self, *, session_tag: str) -> RunArtifacts:
        proxy_payload = self.proxy_source.fetch_proxy()
        proxy = ProxyRecord.from_mapping(proxy_payload)
        sub2api_proxy_id = self.sub2api.sync_proxy(proxy)
        clash_result = self.clash.apply_proxy(proxy)
        adspower_proxy_id = ""
        adspower_profile_id = ""
        browser = ""
        browser_profile_dir = ""
        browser_start_url = ""
        if self.adspower is not None:
            adspower_proxy_id = self.adspower.add_proxy(proxy)
            adspower_profile_id = self.adspower.create_profile_with_local_proxy(
                proxy,
                local_host=clash_result.local_host,
                local_port=clash_result.local_port,
            )
        if self.browser_adapter is not None:
            browser_result = self.browser_adapter.launch_with_local_proxy(
                proxy,
                local_host=clash_result.local_host,
                local_port=clash_result.local_port,
            )
            browser = getattr(browser_result, "browser", "")
            browser_profile_dir = getattr(browser_result, "profile_dir", "")
            browser_start_url = getattr(browser_result, "start_url", "")
        validation = ValidationResult(
            status="SKIPPED",
            stage="browser_validation_not_run",
            reasons=["browser_validation_not_run"],
            checks={
                "local_proxy_host": clash_result.local_host,
                "local_proxy_port": clash_result.local_port,
                "clash_reload_status": getattr(clash_result, "reload_status", "skipped"),
                "adspower_profile_id": adspower_profile_id,
                "browser": browser,
                "browser_profile_dir": browser_profile_dir,
                "browser_start_url": browser_start_url,
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
            browser=browser,
            browser_profile_dir=browser_profile_dir,
            browser_start_url=browser_start_url,
        )
        Reporter(base_dir=self.report_base_dir).write_run_report(artifacts)
        return artifacts
