from autoproxy.adapters.adspower_adapter import AdsPowerAdapter
from autoproxy.models import ProxyRecord


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *, proxies=None, profiles=None):
        self.calls = []
        self.proxies = proxies or []
        self.profiles = profiles or []

    def get(self, url, *, headers, params=None, timeout):
        self.calls.append(("GET", url, params, headers))
        if url.endswith("/api/v1/user/list"):
            return FakeResponse({"code": 0, "msg": "Success", "data": {"list": self.profiles}})
        return FakeResponse({"code": 0, "msg": "Success", "data": {"list": []}})

    def post(self, url, *, json, headers, timeout):
        self.calls.append(("POST", url, json, headers))
        if url.endswith("/api/v2/proxy-list/list"):
            return FakeResponse(
                {
                    "code": 0,
                    "msg": "Success",
                    "data": {"list": self.proxies, "total": len(self.proxies)},
                }
            )
        if url.endswith("/api/v2/proxy-list/create"):
            return FakeResponse({"code": 0, "msg": "Success", "data": {"proxy_id": ["1"]}})
        return FakeResponse({"code": 0, "msg": "Success", "data": {"id": "profile-001"}})


def test_adspower_adds_proxy_list_entry_from_record():
    session = FakeSession()
    adapter = AdsPowerAdapter(
        base_url="http://127.0.0.1:50325",
        api_key="key",
        session=session,
    )
    record = ProxyRecord.from_mapping(
        {
            "id": "proxy-002",
            "name": "devtest",
            "type": "socks5",
            "host": "9.8.7.6",
            "port": 54321,
            "username": "testuser",
            "password": "testpass",
        }
    )

    proxy_id = adapter.add_proxy(record)

    method, url, payload, headers = session.calls[-1]
    assert proxy_id == "1"
    assert method == "POST"
    assert url == "http://127.0.0.1:50325/api/v2/proxy-list/create"
    assert payload == [
        {
            "type": "socks5",
            "host": "9.8.7.6",
            "port": "54321",
            "user": "testuser",
            "password": "testpass",
            "remark": "devtest",
        }
    ]
    assert headers["Authorization"] == "Bearer key"


def test_adspower_reuses_existing_proxy_entry():
    session = FakeSession(
        proxies=[
            {
                "proxy_id": "existing-proxy",
                "type": "socks5",
                "host": "9.8.7.6",
                "port": "54321",
                "user": "testuser",
                "password": "testpass",
                "remark": "devtest",
            }
        ]
    )
    adapter = AdsPowerAdapter(
        base_url="http://127.0.0.1:50325",
        api_key="key",
        session=session,
    )
    record = ProxyRecord.from_mapping(
        {
            "id": "proxy-002",
            "name": "devtest",
            "type": "socks5",
            "host": "9.8.7.6",
            "port": 54321,
            "username": "testuser",
            "password": "testpass",
        }
    )

    proxy_id = adapter.add_proxy(record)

    assert proxy_id == "existing-proxy"
    assert not any(call[1].endswith("/api/v2/proxy-list/create") for call in session.calls)


def test_adspower_creates_profile_with_local_socks_proxy():
    session = FakeSession()
    adapter = AdsPowerAdapter(
        base_url="http://127.0.0.1:50325",
        api_key="key",
        session=session,
    )
    record = ProxyRecord.from_mapping(
        {
            "id": "proxy-003",
            "name": "local-socks",
            "type": "socks5",
            "host": "198.51.100.30",
            "port": 1080,
        }
    )

    profile_id = adapter.create_profile_with_local_proxy(
        record,
        local_host="127.0.0.1",
        local_port=7891,
    )

    method, url, payload, _ = session.calls[-1]
    assert profile_id == "profile-001"
    assert method == "POST"
    assert url == "http://127.0.0.1:50325/api/v1/user/create"
    assert payload["name"] == "local-socks"
    assert payload["group_id"] == "0"
    assert payload["user_proxy_config"] == {
        "proxy_soft": "other",
        "proxy_type": "socks5",
        "proxy_host": "127.0.0.1",
        "proxy_port": "7891",
    }


def test_adspower_reuses_existing_profile_by_name():
    session = FakeSession(
        profiles=[
            {
                "user_id": "existing-profile",
                "name": "local-socks",
                "user_proxy_config": {
                    "proxy_host": "127.0.0.1",
                    "proxy_port": "7891",
                },
            }
        ]
    )
    adapter = AdsPowerAdapter(
        base_url="http://127.0.0.1:50325",
        api_key="key",
        session=session,
    )
    record = ProxyRecord.from_mapping(
        {
            "id": "proxy-003",
            "name": "local-socks",
            "type": "socks5",
            "host": "198.51.100.30",
            "port": 1080,
        }
    )

    profile_id = adapter.create_profile_with_local_proxy(
        record,
        local_host="127.0.0.1",
        local_port=7891,
    )

    assert profile_id == "existing-profile"
    assert not any(call[1].endswith("/api/v1/user/create") for call in session.calls)
