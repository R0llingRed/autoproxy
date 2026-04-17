from autoproxy.adapters.openbao_source import OpenBaoProxySource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.last_url = None
        self.last_headers = None
        self.posts = []

    def get(self, url, *, headers, timeout):
        self.last_url = url
        self.last_headers = headers
        return FakeResponse(
            {
                "data": {
                    "data": {
                        "name": "devtest",
                        "type": "socks5",
                        "host": "1.2.3.4",
                        "port": 5678,
                        "username": "testuser",
                        "password": "test123",
                        "country": "US",
                    }
                }
            }
        )

    def post(self, url, *, json, headers, timeout):
        self.posts.append((url, json, headers))
        return FakeResponse({"data": {"version": 1}})


def test_openbao_source_reads_kv_v2_proxy():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        secret_path="autoproxy/proxies/proxy-002",
        session=session,
    )

    payload = source.fetch_proxy()

    assert session.last_url == "http://127.0.0.1:8200/v1/secret/data/autoproxy/proxies/proxy-002"
    assert session.last_headers["X-Vault-Token"] == "secret-token"
    assert payload["id"] == "proxy-002"
    assert payload["name"] == "devtest"
    assert payload["provider"] == "openbao"
    assert payload["host"] == "1.2.3.4"


def test_openbao_source_writes_proxy_to_kv_v2():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        secret_path="autoproxy/proxies/proxy-002",
        session=session,
    )

    result = source.write_proxy(
        "proxy-010",
        {
            "name": "file-proxy",
            "type": "socks5",
            "host": "1.2.3.4",
            "port": 5678,
        },
    )

    url, payload, headers = session.posts[0]
    assert result["secret_path"] == "autoproxy/proxies/proxy-010"
    assert url == "http://127.0.0.1:8200/v1/secret/data/autoproxy/proxies/proxy-010"
    assert payload == {
        "data": {
            "name": "file-proxy",
            "type": "socks5",
            "host": "1.2.3.4",
            "port": 5678,
        }
    }
    assert headers["X-Vault-Token"] == "secret-token"


def test_openbao_source_imports_proxy_json_file(tmp_path):
    source_file = tmp_path / "proxies.json"
    source_file.write_text(
        """
[
  {
    "id": "proxy-010",
    "name": "file-proxy-1",
    "type": "socks5",
    "host": "1.2.3.4",
    "port": 5678
  },
  {
    "id": "proxy-011",
    "name": "file-proxy-2",
    "raw_uri": "socks5://user:pass@5.6.7.8:6789"
  }
]
"""
    )
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        secret_path="autoproxy/proxies/proxy-002",
        session=session,
    )

    results = source.write_proxies_from_file(source_file)

    assert [item["secret_path"] for item in results] == [
        "autoproxy/proxies/proxy-010",
        "autoproxy/proxies/proxy-011",
    ]
    assert len(session.posts) == 2
