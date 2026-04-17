import json
import importlib.util
from pathlib import Path


def load_cli_module():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("autoproxy_cli", root / "autoproxy.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeProxySource:
    def __init__(self):
        self.imported_file = None

    def fetch_proxy(self):
        return {
            "id": "proxy-001",
            "name": "devtest",
            "type": "socks5",
            "host": "1.2.3.4",
            "port": 5678,
            "username": "user",
            "password": "pass",
            "provider": "fake",
        }

    def write_proxies_from_file(self, path):
        self.imported_file = str(path)
        return [{"secret_path": "autoproxy/proxies/proxy-010"}]


class FakeSub2Api:
    def sync_proxy(self, record):
        return "sub2api-1"


class FakeClash:
    def apply_proxy(self, record):
        class Result:
            node_name = "auto-chain-fake-devtest"
            listener_name = "auto-listener-fake-devtest"
            local_host = "127.0.0.1"
            local_port = 7890

        return Result()


class FakeAdsPower:
    def add_proxy(self, record):
        return "ads-proxy-1"

    def create_profile_with_local_proxy(self, record, *, local_host, local_port):
        return f"profile-{local_port}"


def write_config(tmp_path: Path) -> Path:
    config = {
        "proxy_source": {"type": "fake"},
        "sub2api": {},
        "clash": {"config_path": str(tmp_path / "clash.yaml")},
        "adspower": {},
        "report_base_dir": str(tmp_path / "docs"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


def install_fakes(monkeypatch, autoproxy_cli):
    monkeypatch.setattr(autoproxy_cli, "build_proxy_source", lambda config: FakeProxySource())
    monkeypatch.setattr(autoproxy_cli, "build_sub2api", lambda config: FakeSub2Api())
    monkeypatch.setattr(autoproxy_cli, "build_clash", lambda config: FakeClash())
    monkeypatch.setattr(autoproxy_cli, "build_adspower", lambda config: FakeAdsPower())


def test_cli_openbao_get_outputs_proxy(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "openbao-get"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["name"] == "devtest"


def test_cli_openbao_import_outputs_written_paths(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)
    import_file = tmp_path / "proxies.json"
    import_file.write_text("[]")

    assert (
        autoproxy_cli.main(
            ["--config", str(config_path), "openbao-import", "--file", str(import_file)]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["written"][0]["secret_path"] == "autoproxy/proxies/proxy-010"


def test_cli_clash_write_outputs_listener(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "clash-write"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["local_port"] == 7890


def test_cli_adspower_create_profile_uses_clash_listener(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "adspower-create-profile"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["adspower_profile_id"] == "profile-7890"


def test_cli_run_keeps_full_flow(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "run", "--session-tag", "cli-test"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["session_tag"] == "cli-test"
    assert output["adspower_profile_id"] == "profile-7890"
