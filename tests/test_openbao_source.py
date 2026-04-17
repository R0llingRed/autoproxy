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
        self.requests = []

    def get(self, url, *, headers, timeout):
        self.last_url = url
        self.last_headers = headers
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

    def post(self, url, *, json, headers, timeout):
        self.posts.append((url, json, headers))
        return FakeResponse({"data": {"version": 1}})

    def request(self, method, url, *, headers, timeout):
        self.requests.append((method, url, headers, timeout))
        return FakeResponse({"data": {"keys": ["proxy-001", "proxy-002", "nested/"]}})


def test_openbao_source_reads_kv_v2_proxy():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        read_path="autoproxy/proxies/proxy-001",
        import_prefix="autoproxy/proxies",
        session=session,
    )

    payload = source.fetch_proxy()

    assert session.last_url == "http://127.0.0.1:8200/v1/secret/data/autoproxy/proxies/proxy-001"
    assert session.last_headers["X-Vault-Token"] == "secret-token"
    assert payload["id"] == "proxy-001"
    assert payload["name"] == "devtest"
    assert payload["provider"] == "openbao"
    assert payload["host"] == "1.2.3.4"


def test_openbao_source_writes_proxy_to_kv_v2():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        read_path="autoproxy/proxies/proxy-001",
        import_prefix="autoproxy/proxies",
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
        read_path="autoproxy/proxies/proxy-001",
        import_prefix="autoproxy/proxies",
        session=session,
    )

    results = source.write_proxies_from_file(source_file)

    assert [item["secret_path"] for item in results] == [
        "autoproxy/proxies/proxy-010",
        "autoproxy/proxies/proxy-011",
    ]
    assert len(session.posts) == 2


def test_openbao_source_lists_proxy_ids_from_import_prefix():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="autoproxy/proxies",
        session=session,
    )

    proxy_ids = source.list_proxy_ids()

    assert proxy_ids == ["proxy-001", "proxy-002"]
    method, url, headers, timeout = session.requests[0]
    assert method == "LIST"
    assert url == "http://127.0.0.1:8200/v1/secret/metadata/autoproxy/proxies"
    assert headers["X-Vault-Token"] == "secret-token"
    assert timeout == 10.0


def test_openbao_source_fetches_proxy_by_id_from_import_prefix():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="autoproxy/proxies",
        session=session,
    )

    payload = source.fetch_proxy_by_id("proxy-002")

    assert session.last_url == "http://127.0.0.1:8200/v1/secret/data/autoproxy/proxies/proxy-002"
    assert payload["id"] == "proxy-002"
    assert payload["name"] == "backup"


def test_openbao_source_fetches_all_proxies():
    session = FakeSession()
    source = OpenBaoProxySource(
        base_url="http://127.0.0.1:8200",
        token="secret-token",
        mount="secret",
        import_prefix="autoproxy/proxies",
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
        import_prefix="autoproxy/proxies",
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
        import_prefix="autoproxy/proxies",
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
