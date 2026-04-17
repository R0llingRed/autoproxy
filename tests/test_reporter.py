import json
from pathlib import Path

from autoproxy.models import ProxyRecord, RunArtifacts, ValidationResult
from autoproxy.reporter import Reporter


def test_reporter_writes_json_and_markdown(tmp_path: Path):
    reporter = Reporter(base_dir=tmp_path)
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:1080",
        proxy_id="proxy-123",
        country="US",
        city="Los Angeles",
    )
    result = ValidationResult(
        status="PASS",
        stage="browserleaks",
        reasons=[],
        checks={"ip": "1.2.3.4"},
    )
    artifacts = RunArtifacts(
        session_tag="test001",
        proxy=record,
        sub2api_proxy_id="sub2api-42",
        clash_node_name="openbao-proxy-123",
        validation=result,
        screenshots=["screenshots/ping0.png"],
    )

    paths = reporter.write_run_report(artifacts)

    report = json.loads(paths["json"].read_text())
    markdown = paths["markdown"].read_text()

    assert report["proxy"]["id"] == "proxy-123"
    assert report["sub2api_proxy_id"] == "sub2api-42"
    assert "# AutoProxy Run Report" in markdown
    assert "openbao-proxy-123" in markdown
