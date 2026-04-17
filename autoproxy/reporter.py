from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from autoproxy.models import RunArtifacts


@dataclass(slots=True)
class Reporter:
    base_dir: Path

    def write_run_report(self, artifacts: RunArtifacts) -> dict[str, Path]:
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        report_dir = self.base_dir / "reports" / stamp
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / f"{artifacts.session_tag}.json"
        markdown_path = report_dir / f"{artifacts.session_tag}.md"
        json_path.write_text(
            json.dumps(artifacts.to_dict(), indent=2, ensure_ascii=False) + "\n"
        )
        markdown_path.write_text(self._render_markdown(artifacts))
        return {"json": json_path, "markdown": markdown_path}

    def _render_markdown(self, artifacts: RunArtifacts) -> str:
        lines = [
            "# AutoProxy Run Report",
            "",
            f"- Session: {artifacts.session_tag}",
            f"- Proxy ID: {artifacts.proxy.id}",
            f"- Clash Node: {artifacts.clash_node_name}",
            f"- Sub2API Proxy ID: {artifacts.sub2api_proxy_id}",
            f"- AdsPower Proxy ID: {artifacts.adspower_proxy_id or 'none'}",
            f"- AdsPower Profile ID: {artifacts.adspower_profile_id or 'none'}",
            f"- Validation Status: {artifacts.validation.status}",
            f"- Validation Stage: {artifacts.validation.stage}",
            "",
            "## Reasons",
        ]
        if artifacts.validation.reasons:
            lines.extend(f"- {reason}" for reason in artifacts.validation.reasons)
        else:
            lines.append("- none")
        lines.extend(["", "## Checks"])
        if artifacts.validation.checks:
            lines.extend(
                f"- {key}: {value}"
                for key, value in sorted(artifacts.validation.checks.items())
            )
        else:
            lines.append("- none")
        if artifacts.screenshots:
            lines.extend(["", "## Screenshots"])
            lines.extend(f"- {item}" for item in artifacts.screenshots)
        lines.append("")
        return "\n".join(lines)
