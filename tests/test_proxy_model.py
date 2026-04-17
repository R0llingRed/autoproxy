from autoproxy.models import ProxyRecord


def test_proxy_record_parses_socks5_uri_with_auth():
    record = ProxyRecord.from_uri(
        "socks5://user:pass@1.2.3.4:1080",
        proxy_id="proxy-123",
        country="US",
        city="Los Angeles",
    )

    assert record.id == "proxy-123"
    assert record.type == "socks5"
    assert record.host == "1.2.3.4"
    assert record.port == 1080
    assert record.username == "user"
    assert record.password == "pass"
    assert record.country == "US"
    assert record.city == "Los Angeles"
    assert record.raw_uri == "socks5://user:pass@1.2.3.4:1080"


def test_proxy_record_preserves_human_name_from_mapping():
    record = ProxyRecord.from_mapping(
        {
            "id": "proxy-002",
            "name": "devtest",
            "type": "socks5",
            "host": "1.2.3.4",
            "port": 5678,
            "username": "testuser",
            "password": "test123",
            "provider": "openbao",
        }
    )

    assert record.name == "devtest"
    assert record.node_name == "openbao-devtest"


def test_proxy_record_requires_port_in_uri():
    try:
        ProxyRecord.from_uri("socks5://user:pass@1.2.3.4", proxy_id="proxy-123")
    except ValueError as exc:
        assert "port" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
