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


def test_resolve_env_expands_nested_list_dict(monkeypatch):
    autoproxy_cli = load_cli_module()
    monkeypatch.setenv("AUTO_PROXY_TEST_TOKEN", "secret-token")

    resolved = autoproxy_cli._resolve_env(
        {"items": [{"token": "${AUTO_PROXY_TEST_TOKEN}"}]}
    )

    assert resolved == {"items": [{"token": "secret-token"}]}


def test_resolve_env_expands_placeholders_inside_strings(monkeypatch):
    autoproxy_cli = load_cli_module()
    monkeypatch.setenv("AUTO_PROXY_HOME", "C:/Users/example")

    resolved = autoproxy_cli._resolve_env("${AUTO_PROXY_HOME}/AutoProxy/config.local.json")

    assert resolved == "C:/Users/example/AutoProxy/config.local.json"


def test_resolve_env_rejects_missing_env_var():
    autoproxy_cli = load_cli_module()

    try:
        autoproxy_cli._resolve_env("${AUTO_PROXY_MISSING_TOKEN}")
    except ValueError as exc:
        assert "AUTO_PROXY_MISSING_TOKEN" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_config_records_config_directory_and_reads_utf8(tmp_path):
    autoproxy_cli = load_cli_module()
    config_dir = tmp_path / "配置"
    config_dir.mkdir()
    config_path = config_dir / "config.local.json"
    config_path.write_text('{"label": "中文"}', encoding="utf-8")

    config = autoproxy_cli.load_config(config_path)

    assert config["label"] == "中文"
    assert config[autoproxy_cli.CONFIG_DIR_KEY] == config_dir


def test_builders_resolve_relative_paths_from_config_directory(tmp_path):
    autoproxy_cli = load_cli_module()
    config_dir = tmp_path / "project"
    config_dir.mkdir()
    config_path = config_dir / "config.local.json"
    config_path.write_text(
        json.dumps(
            {
                "proxy_source": {"type": "txt", "path": "data/proxies.txt"},
                "sub2api": {"base_url": "http://127.0.0.1:8080", "token": "token"},
                "clash": {"config_path": "configs/clash.yaml"},
                "report_base_dir": "docs",
            }
        ),
        encoding="utf-8",
    )

    config = autoproxy_cli.load_config(config_path)
    source = autoproxy_cli.build_proxy_source(config)
    clash = autoproxy_cli.build_clash(config)
    runner = autoproxy_cli.build_runner(config)

    assert source.path == config_dir / "data" / "proxies.txt"
    assert clash.config_path == config_dir / "configs" / "clash.yaml"
    assert runner.report_base_dir == config_dir / "docs"


def test_cli_openbao_get_outputs_proxy(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "openbao-get"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["name"] == "devtest"


def test_cli_uses_config_local_json_by_default(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    write_config(tmp_path).rename(tmp_path / "config.local.json")
    monkeypatch.chdir(tmp_path)

    assert autoproxy_cli.main(["openbao-get"]) == 0

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
