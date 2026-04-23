import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "openbao-tool" / "openbao_tool.py"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.collection = {
            "proxy-001": {
                "name": "devtest",
                "type": "socks5",
                "host": "1.2.3.4",
                "port": 5678,
            }
        }
        self.gets = []
        self.posts = []

    def get(self, url, *, headers, timeout, verify=True):
        self.gets.append((url, headers, timeout, verify))
        return FakeResponse({"data": {"data": {"proxies": self.collection}}})

    def post(self, url, *, json, headers, timeout, verify=True):
        self.posts.append((url, json, headers, timeout, verify))
        self.collection = dict(json["data"]["proxies"])
        return FakeResponse({"data": {"version": 2}})


def load_tool():
    spec = importlib.util.spec_from_file_location("openbao_tool", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["openbao_tool"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenBaoToolTests(unittest.TestCase):
    def test_standalone_tool_fetches_proxy_by_id_without_project_imports(self):
        tool = load_tool()
        session = FakeSession()
        source = tool.OpenBaoProxySource(
            base_url="http://127.0.0.1:8200",
            token="secret-token",
            import_prefix="external/proxies",
            session=session,
        )

        payload = source.fetch_proxy_by_id("proxy-001")

        self.assertEqual(
            payload,
            {
                "id": "proxy-001",
                "provider": "openbao",
                "name": "devtest",
                "type": "socks5",
                "host": "1.2.3.4",
                "port": 5678,
            },
        )
        self.assertEqual(
            session.gets[0][0],
            "http://127.0.0.1:8200/v1/secret/data/external/proxies",
        )

    def test_standalone_tool_imports_proxy_json_file(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "proxies.json"
            source_file.write_text(
                json.dumps(
                    [
                        {
                            "id": "proxy-010",
                            "name": "file-proxy",
                            "raw_uri": "socks5://user:pass@5.6.7.8:6789",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            session = FakeSession()
            source = tool.OpenBaoProxySource(
                base_url="http://127.0.0.1:8200",
                token="secret-token",
                import_prefix="external/proxies",
                now_provider=lambda: tool.datetime(2026, 4, 21, 10, 30, 0, tzinfo=tool.UTC),
                session=session,
            )

            results = source.write_proxies_from_file(source_file)

        self.assertEqual(results[0]["id"], "proxy-010")
        self.assertEqual(
            session.posts[0][1]["data"]["proxies"]["proxy-010"],
            {
                "name": "file-proxy",
                "raw_uri": "socks5://user:pass@5.6.7.8:6789",
                "updated_at": "2026-04-21T10:30:00Z",
                "updated_by": "user",
            },
        )


if __name__ == "__main__":
    unittest.main()
