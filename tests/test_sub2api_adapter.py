from autoproxy.adapters.sub2api_adapter import Sub2ApiAdapter
from autoproxy.models import ProxyRecord


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *, proxies=None):
        self.calls = []
        self.proxies = proxies or []

    def post(self, url, *, json, headers, timeout):
        self.calls.append(("POST", url, json, headers))
        if url.endswith("/api/v1/auth/login"):
            return FakeResponse({"code": 0, "data": {"access_token": "token"}})
        return FakeResponse({"code": 0, "data": {"id": 42}})

    def get(self, url, *, params, headers, timeout):
        self.calls.append(("GET", url, params, headers))
        return FakeResponse({"code": 0, "data": {"items": self.proxies}})


class PagedFakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append(("POST", url, json, headers))
        if url.endswith("/api/v1/auth/login"):
            return FakeResponse({"code": 0, "data": {"access_token": "token"}})
        return FakeResponse({"code": 0, "data": {"id": 42}})

    def get(self, url, *, params, headers, timeout):
        self.calls.append(("GET", url, params, headers))
        if params["page"] == 1:
            return FakeResponse({"code": 0, "data": {"items": [{"id": 1}], "total": 21}})
        return FakeResponse(
            {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "id": 7,
                            "protocol": "socks5",
                            "host": "1.2.3.4",
                            "port": 1080,
                            "username": "user",
                        }
                    ],
                    "total": 21,
                },
            }
        )


def test_sub2api_builds_proxy_payload():
    adapter = Sub2ApiAdapter(base_url="https://sub2api.example.com", token="secret")
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:1080",
        proxy_id="proxy-123",
        country="US",
        city="Los Angeles",
    )

    payload = adapter.build_proxy_payload(record)

    assert payload["name"] == "openbao-proxy-123"
    assert payload["protocol"] == "socks5"
    assert payload["host"] == "1.2.3.4"
    assert payload["port"] == 1080
    assert payload["username"] == "user"
    assert payload["password"] == "pass"
    assert payload["status"] == 1
    assert payload["remark"] == "US/Los Angeles"


def test_sub2api_natural_key_is_stable():
    adapter = Sub2ApiAdapter(base_url="https://sub2api.example.com", token="secret")
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:1080",
        proxy_id="proxy-123",
    )

    assert adapter.natural_key(record) == "socks5|1.2.3.4|1080|user"


def test_sub2api_builds_login_payload():
    adapter = Sub2ApiAdapter(
        base_url="https://sub2api.example.com",
        email="admin@sub2api.local",
        password="secret",
    )

    payload = adapter.build_login_payload()

    assert payload == {"email": "admin@sub2api.local", "password": "secret"}


def test_sub2api_builds_proxy_list_params():
    adapter = Sub2ApiAdapter(base_url="https://sub2api.example.com", token="secret")

    params = adapter.build_proxy_list_params()

    assert params == {
        "page": 1,
        "page_size": 20,
        "status": "",
        "timezone": "Asia/Shanghai",
    }


def test_sub2api_reuses_existing_proxy():
    session = FakeSession(
        proxies=[
            {
                "id": 7,
                "protocol": "socks5",
                "host": "1.2.3.4",
                "port": 1080,
                "username": "user",
            }
        ]
    )
    adapter = Sub2ApiAdapter(
        base_url="https://sub2api.example.com",
        email="admin@sub2api.local",
        password="secret",
        create_path="/api/v1/admin/proxies",
        session=session,
    )
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:1080",
        proxy_id="proxy-123",
    )

    proxy_id = adapter.sync_proxy(record)

    assert proxy_id == "7"
    assert not any(
        call[0] == "POST" and call[1].endswith("/api/v1/admin/proxies")
        for call in session.calls
    )


def test_sub2api_reuses_existing_proxy_found_on_later_page():
    session = PagedFakeSession()
    adapter = Sub2ApiAdapter(
        base_url="https://sub2api.example.com",
        email="admin@sub2api.local",
        password="secret",
        create_path="/api/v1/admin/proxies",
        session=session,
    )
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:1080",
        proxy_id="proxy-123",
    )

    proxy_id = adapter.sync_proxy(record)

    assert proxy_id == "7"
    pages = [call[2]["page"] for call in session.calls if call[0] == "GET"]
    assert pages == [1, 2]
    assert not any(
        call[0] == "POST" and call[1].endswith("/api/v1/admin/proxies")
        for call in session.calls
    )


def test_sub2api_creates_keys_in_batch():
    session = FakeSession()
    adapter = Sub2ApiAdapter(
        base_url="https://sub2api.example.com",
        token="secret",
        session=session,
    )

    result = adapter.create_keys_bulk(
        [
            {"name": "test-a", "group_id": 1},
            {"name": "test-b", "group_id": 2},
        ]
    )

    assert len(result) == 2
    assert result[0]["name"] == "test-a"
    assert result[1]["name"] == "test-b"
    assert result[0]["group_id"] == 1
    assert result[1]["group_id"] == 2
    create_calls = [call for call in session.calls if call[0] == "POST"]
    assert create_calls[0][1].endswith("/api/v1/keys")
    assert create_calls[0][2] == {"name": "test-a", "group_id": 1}
    assert create_calls[1][2] == {"name": "test-b", "group_id": 2}
