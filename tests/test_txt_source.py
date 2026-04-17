from pathlib import Path

from autoproxy.adapters.txt_source import TxtProxySource


def test_txt_source_reads_first_proxy_uri(tmp_path: Path):
    source_file = tmp_path / "proxies.txt"
    source_file.write_text(
        "# comment\n\nsocks5://user:pass@1.2.3.4:1080\nsocks5://user2:pass2@5.6.7.8:2080\n"
    )

    source = TxtProxySource(path=source_file)

    proxy = source.fetch_proxy()

    assert proxy["raw_uri"] == "socks5://user:pass@1.2.3.4:1080"
    assert proxy["provider"] == "txt"
    assert proxy["id"].startswith("txt-")


def test_txt_source_rejects_empty_file(tmp_path: Path):
    source_file = tmp_path / "proxies.txt"
    source_file.write_text("# comment only\n")

    source = TxtProxySource(path=source_file)

    try:
        source.fetch_proxy()
    except ValueError as exc:
        assert "no proxy entries" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
