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
            reload_status = "reloaded"

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
    assert artifacts.validation.checks["clash_reload_status"] == "reloaded"


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


class FakeBrowserAdapter:
    def __init__(self):
        self.calls = []

    def launch_with_local_proxy(self, record, *, local_host, local_port):
        self.calls.append((record.id, local_host, local_port))
        return type(
            "Result",
            (),
            {
                "browser": "camoufox",
                "profile_dir": "/tmp/camoufox/proxy-123",
                "start_url": "https://www.browserscan.net",
                "to_dict": lambda self: {
                    "browser": "camoufox",
                    "profile_dir": "/tmp/camoufox/proxy-123",
                    "start_url": "https://www.browserscan.net",
                },
            },
        )()


def test_runner_launches_browser_adapter_with_clash_listener(tmp_path):
    browser = FakeBrowserAdapter()
    runner = FlowRunner(
        proxy_source=FakeProxySource(),
        sub2api=FakeSub2ApiAdapter(),
        clash=FakeClashAdapter(),
        report_base_dir=tmp_path,
        browser_adapter=browser,
    )

    artifacts = runner.run(session_tag="test001")

    assert browser.calls == [("proxy-123", "127.0.0.1", 7890)]
    assert artifacts.browser == "camoufox"
    assert artifacts.browser_profile_dir == "/tmp/camoufox/proxy-123"
    assert artifacts.browser_start_url == "https://www.browserscan.net"
    assert artifacts.validation.checks["browser"] == "camoufox"
