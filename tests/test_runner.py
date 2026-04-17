from autoproxy.runner import FlowRunner


class FakeProxySource:
    def fetch_proxy(self):
        return {
            "id": "proxy-123",
            "raw_uri": "socks5://user:pass@1.2.3.4:1080",
            "country": "US",
            "city": "Los Angeles",
        }


class FakeSub2ApiAdapter:
    def sync_proxy(self, record):
        return "sub2api-42"


class FakeClashAdapter:
    def apply_proxy(self, record):
        class Result:
            node_name = "openbao-proxy-123"
            local_host = "127.0.0.1"
            local_port = 7890

        return Result()


def test_runner_executes_full_flow(tmp_path):
    runner = FlowRunner(
        proxy_source=FakeProxySource(),
        sub2api=FakeSub2ApiAdapter(),
        clash=FakeClashAdapter(),
        report_base_dir=tmp_path,
    )

    artifacts = runner.run(session_tag="test001")

    assert artifacts.proxy.id == "proxy-123"
    assert artifacts.sub2api_proxy_id == "sub2api-42"
    assert artifacts.clash_node_name == "openbao-proxy-123"
    assert artifacts.validation.status == "SKIPPED"


class FakeAdsPowerAdapter:
    def add_proxy(self, record):
        return "adspower-proxy-1"

    def create_profile_with_local_proxy(self, record, *, local_host, local_port):
        assert local_host == "127.0.0.1"
        assert local_port == 7890
        return "profile-1"


def test_runner_creates_adspower_profile_with_clash_listener(tmp_path):
    runner = FlowRunner(
        proxy_source=FakeProxySource(),
        sub2api=FakeSub2ApiAdapter(),
        clash=FakeClashAdapter(),
        report_base_dir=tmp_path,
        adspower=FakeAdsPowerAdapter(),
    )

    artifacts = runner.run(session_tag="test001")

    assert artifacts.adspower_proxy_id == "adspower-proxy-1"
    assert artifacts.adspower_profile_id == "profile-1"
    assert artifacts.validation.checks["local_proxy_port"] == 7890
