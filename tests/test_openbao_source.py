from datetime import datetime, UTC

from autoproxy.adapters.openbao_source import OpenBaoProxySource
from requests import HTTPError


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class NotFoundResponse:
    status_code = 404

    def raise_for_status(self):
        raise HTTPError("404 Client Error: Not Found", response=self)

    def json(self):
        return {"errors": []}


class FakeSession:
    def __init__(self):
        self.last_url = None
        self.last_headers = None
        self.last_verify = None
        self.gets = []
        self.posts = []
        self.requests = []
        self.collection = {
            "proxy-001": {
                "name": "devtest",
                "type": "socks5",
                "host": "1.2.3.4",
                "port": 5678,
                "username": "testuser",
                "password": "test123",
                "country": "US",
            },
            "proxy-002": {
                "name": "backup",
                "type": "socks5",
                "host": "5.6.7.8",
                "port": 6789,
                "username": "backup",
                "password": "secret",
                "country": "SG",
            },
        }

    def get(self, url, *, headers, timeout, verify=True):
        self.last_url = url
        self.last_headers = headers
        self.last_verify = verify
        self.gets.append((url, headers, timeout, verify))
        path = url.split("/v1/", 1)[-1]
        if path == "secret/data/external/proxies":
            return FakeResponse({"data": {"data": {"proxies": self.collection}}})
        proxy_id = url.rstrip("/").split("/")[-1]
        return FakeResponse(
            {
                "data": {
                    "data": {
                        "name": {
                            "proxy-001": "devtest",
                            "proxy-002": "backup",
                        }.get(proxy_id, "file-proxy"),
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

    def post(self, url, *, json, headers, timeout, verify=True):
        self.last_verify = verify
        self.posts.append((url, json, headers, verify))
        if url.endswith("/v1/secret/data/external/proxies"):
            self.collection = dict(json["data"]["proxies"])
        return FakeResponse({"data": {"version": 1}})

    def request(self, method, url, *, headers, timeout):
        self.requests.append((method, url, headers, timeout))
        return FakeResponse({"data": {"keys": ["proxy-001", "proxy-002", "nested/"]}})


class MissingPrefixSession(FakeSession):
    def get(self, url, *, headers, timeout, verify=True):
        self.gets.append((url, headers, timeout, verify))
        return NotFoundResponse()


def test_openbao_source_passes_custom_ca_bundle_to_requests():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="https://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="external/proxies",
        ca_cert_path="D:/whfiles/openbao/tls/ca.pem",
        session=session,
    )

    source.fetch_all_proxies()

    assert session.last_verify == "D:/whfiles/openbao/tls/ca.pem"


def test_openbao_source_reads_kv_v2_proxy():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        read_path="external/proxies",
        import_prefix="external/proxies",
        session=session,
    )

    payload = source.fetch_proxy_by_id("proxy-001")

    assert session.last_url == "http://127.0.0.1:8200/v1/secret/data/external/proxies"
    assert session.last_headers["X-Vault-Token"] == "secret-token"
    assert payload["id"] == "proxy-001"
    assert payload["name"] == "devtest"
    assert payload["provider"] == "openbao"
    assert payload["host"] == "1.2.3.4"


def test_openbao_source_writes_proxy_to_kv_v2():
    session = FakeSession()
    fixed_now = datetime(2026, 4, 21, 10, 30, 0, tzinfo=UTC)
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        read_path="external/proxies",
        import_prefix="external/proxies",
        now_provider=lambda: fixed_now,
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
    assert result["secret_path"] == "external/proxies"
    assert url == "http://127.0.0.1:8200/v1/secret/data/external/proxies"
    assert payload["data"]["proxies"]["proxy-010"] == {
        "name": "file-proxy",
        "type": "socks5",
        "host": "1.2.3.4",
        "port": 5678,
        "updated_at": "2026-04-21T10:30:00Z",
        "updated_by": "system",
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
    fixed_now = datetime(2026, 4, 21, 10, 30, 0, tzinfo=UTC)
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        read_path="external/proxies",
        import_prefix="external/proxies",
        now_provider=lambda: fixed_now,
        session=session,
    )

    results = source.write_proxies_from_file(source_file)

    assert [item["secret_path"] for item in results] == [
        "external/proxies",
        "external/proxies",
    ]
    assert len(session.posts) == 1
    written = session.posts[0][1]["data"]["proxies"]
    assert written["proxy-010"]["updated_at"] == "2026-04-21T10:30:00Z"
    assert written["proxy-010"]["updated_by"] == "user"
    assert written["proxy-011"]["updated_at"] == "2026-04-21T10:30:00Z"
    assert written["proxy-011"]["updated_by"] == "user"


def test_openbao_source_lists_proxy_ids_from_import_prefix():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="external/proxies",
        session=session,
    )

    proxy_ids = source.list_proxy_ids()

    assert proxy_ids == ["proxy-001", "proxy-002"]
    url, headers, timeout = session.gets[0]
    assert url == "http://127.0.0.1:8200/v1/secret/data/external/proxies"
    assert headers["X-Vault-Token"] == "secret-token"
    assert timeout == 10.0


def test_openbao_source_returns_empty_list_when_import_prefix_is_missing():
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="external/proxies",
        session=MissingPrefixSession(),
    )

    assert source.list_proxy_ids() == []
    assert source.fetch_all_proxies() == []
    assert source.grep_proxies("real") == []


def test_openbao_source_fetches_proxy_by_id_from_import_prefix():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="external/proxies",
        session=session,
    )

    payload = source.fetch_proxy_by_id("proxy-002")

    assert session.last_url == "http://127.0.0.1:8200/v1/secret/data/external/proxies"
    assert payload["id"] == "proxy-002"
    assert payload["name"] == "backup"


def test_openbao_source_fetches_all_proxies():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="external/proxies",
        session=session,
    )

    payload = source.fetch_all_proxies()

    assert [item["id"] for item in payload] == ["proxy-001", "proxy-002"]


def test_openbao_source_finds_proxies_by_name():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="external/proxies",
        session=session,
    )

    payload = source.find_proxies_by_name("backup")

    assert [item["id"] for item in payload] == ["proxy-002"]


def test_openbao_source_grep_matches_any_field_case_insensitive():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="external/proxies",
        session=session,
    )

    payload = source.grep_proxies("BACKUP")

    assert [item["id"] for item in payload] == ["proxy-002"]


def test_openbao_source_grep_returns_empty_list_when_no_field_matches():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="autoproxy/proxies",
        session=session,
    )

    payload = source.grep_proxies("not-found")

    assert payload == []


def test_openbao_source_keeps_secret_path_as_legacy_read_path():
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
    assert payload["id"] == "proxy-002"
