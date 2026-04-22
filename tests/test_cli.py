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
        return [{"secret_path": "external/proxies"}]

    def fetch_all_proxies(self):
        return [
            {
                "id": "proxy-001",
                "name": "devtest",
                "type": "socks5",
                "host": "1.2.3.4",
                "port": 5678,
                "provider": "fake",
            },
            {
                "id": "proxy-011",
                "name": "backup",
                "type": "socks5",
                "host": "5.6.7.8",
                "port": 6789,
                "provider": "fake",
            }
        ]

    def fetch_proxy_by_id(self, proxy_id):
        return {
            "id": proxy_id,
            "name": "by-id",
            "type": "socks5",
            "host": "1.2.3.4",
            "port": 5678,
            "provider": "fake",
        }

    def find_proxies_by_name(self, name):
        return [
            {
                "id": "proxy-002",
                "name": name,
                "type": "socks5",
                "host": "1.2.3.4",
                "port": 5678,
                "provider": "fake",
            }
        ]

    def grep_proxies(self, keyword):
        normalized = keyword.casefold()
        return [
            item
            for item in self.fetch_all_proxies()
            if normalized in json.dumps(item, ensure_ascii=False).casefold()
        ]


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


class FakeCamoufox:
    def list_templates(self):
        return [{"name": "desktop-humanized", "geoip": True}]

    def get_template(self, name):
        return {"name": name, "geoip": True, "headless": False}

    def list_bindings(self):
        return [
            {
                "proxy_id": "proxy-001",
                "proxy_name": "devtest",
                "local_host": "127.0.0.1",
                "local_port": 7890,
                "proxy_server": "socks5://127.0.0.1:7890",
                "profile_dir": "/tmp/profile",
                "start_url": "https://www.browserscan.net",
            }
        ]

    def get_binding(self, proxy_id):
        return {"proxy_id": proxy_id, "local_port": 7890}

    def launch_with_local_proxy(
        self,
        record,
        *,
        local_host,
        local_port,
        template_name=None,
        keep_open=True,
    ):
        return type(
            "Result",
            (),
            {
                "to_dict": lambda self: {
                    "browser": "camoufox",
                    "proxy_id": record.id,
                    "template_name": template_name,
                    "local_host": local_host,
                    "local_port": local_port,
                    "proxy_server": f"socks5://{local_host}:{local_port}",
                    "profile_dir": "/tmp/profile",
                    "start_url": "https://www.browserscan.net",
                }
            },
        )()


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
    monkeypatch.setattr(autoproxy_cli, "build_camoufox", lambda config: FakeCamoufox())


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


def test_resolve_env_uses_empty_default_for_optional_missing_env_var():
    autoproxy_cli = load_cli_module()

    resolved = autoproxy_cli._resolve_env("${AUTO_PROXY_OPTIONAL_TOKEN:-}")

    assert resolved == ""


def test_resolve_env_uses_default_value_for_optional_missing_env_var():
    autoproxy_cli = load_cli_module()

    resolved = autoproxy_cli._resolve_env("${AUTO_PROXY_OPTIONAL_HOST:-127.0.0.1}")

    assert resolved == "127.0.0.1"


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


def test_build_proxy_source_uses_read_path_and_import_prefix(tmp_path):
    autoproxy_cli = load_cli_module()
    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        json.dumps(
            {
                "proxy_source": {
                    "type": "openbao",
                    "base_url": "http://127.0.0.1:8200",
                    "token": "token",
                    "mount": "secret",
                    "read_path": "autoproxy/proxies/proxy-001",
                    "import_prefix": "autoproxy/proxies",
                }
            }
        ),
        encoding="utf-8",
    )

    config = autoproxy_cli.load_config(config_path)
    source = autoproxy_cli.build_proxy_source(config)

    assert source.read_path == "autoproxy/proxies/proxy-001"
    assert source.import_prefix == "autoproxy/proxies"


def test_build_clash_passes_reload_controller_settings(tmp_path):
    autoproxy_cli = load_cli_module()
    config_dir = tmp_path / "project"
    config_dir.mkdir()
    config_path = config_dir / "config.local.json"
    config_path.write_text(
        json.dumps(
            {
                "clash": {
                    "base_proxy_name": "A",
                    "write_mode": "script",
                    "config_path": "configs/active.yaml",
                    "script_path": "profiles/Script.js",
                    "profiles_path": "profiles.yaml",
                    "profile_dir": "profiles",
                    "reload_after_write": True,
                    "controller_url": "http://127.0.0.1:9090",
                    "controller_secret": "secret",
                    "reload_force": False,
                    "timeout": 3.0,
                }
            }
        ),
        encoding="utf-8",
    )

    config = autoproxy_cli.load_config(config_path)
    clash = autoproxy_cli.build_clash(config)

    assert clash.config_path == config_dir / "configs" / "active.yaml"
    assert clash.write_mode == "script"
    assert clash.script_path == config_dir / "profiles" / "Script.js"
    assert clash.profiles_path == config_dir / "profiles.yaml"
    assert clash.profile_dir == config_dir / "profiles"
    assert clash.reload_after_write is True
    assert clash.controller_url == "http://127.0.0.1:9090"
    assert clash.controller_secret == "secret"
    assert clash.reload_force is False
    assert clash.timeout == 3.0


def test_build_proxy_source_defaults_to_shared_external_proxies_path():
    autoproxy_cli = load_cli_module()

    source = autoproxy_cli.build_proxy_source(
        {
            "proxy_source": {
                "type": "openbao",
                "base_url": "http://127.0.0.1:8200",
                "token": "secret-token",
            }
        }
    )

    assert source.read_path == "external/proxies"
    assert source.import_prefix == "external/proxies"


def test_build_proxy_source_resolves_openbao_ca_cert_path_from_config_directory(tmp_path):
    autoproxy_cli = load_cli_module()
    config_dir = tmp_path / "project"
    config_dir.mkdir()
    config_path = config_dir / "config.local.json"
    config_path.write_text(
        json.dumps(
            {
                "proxy_source": {
                    "type": "openbao",
                    "base_url": "https://127.0.0.1:8200",
                    "token": "secret-token",
                    "ca_cert_path": "tls/ca.pem",
                }
            }
        ),
        encoding="utf-8",
    )

    config = autoproxy_cli.load_config(config_path)
    source = autoproxy_cli.build_proxy_source(config)

    assert Path(source.ca_cert_path).resolve() == (config_dir / "tls" / "ca.pem").resolve()


def test_cli_openbao_get_outputs_proxy(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "openbao-get"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output[0]["name"] == "devtest"


def test_cli_openbao_get_outputs_proxy_by_id(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "openbao-get", "--id", "proxy-123"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["id"] == "proxy-123"
    assert output["name"] == "by-id"


def test_cli_openbao_get_outputs_proxies_by_name(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "openbao-get", "--name", "devtest"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output[0]["id"] == "proxy-002"
    assert output[0]["name"] == "devtest"


def test_cli_openbao_grep_outputs_matching_full_records(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "openbao-grep", "011"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert len(output) == 1
    assert output[0]["id"] == "proxy-011"
    assert output[0]["name"] == "backup"
    assert output[0]["host"] == "5.6.7.8"
    assert output[0]["provider"] == "fake"


def test_cli_uses_config_local_json_by_default(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    write_config(tmp_path).rename(tmp_path / "config.local.json")
    monkeypatch.chdir(tmp_path)

    assert autoproxy_cli.main(["openbao-get"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output[0]["name"] == "devtest"


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
    assert output["written"][0]["secret_path"] == "external/proxies"


def test_cli_sub2api_sync_uses_selected_proxy_id(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "sub2api-sync", "--id", "proxy-123"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["proxy"]["id"] == "proxy-123"
    assert output["proxy"]["name"] == "by-id"


def test_cli_clash_write_uses_selected_proxy_name(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert autoproxy_cli.main(["--config", str(config_path), "clash-write", "--name", "devtest"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["proxy"]["id"] == "proxy-002"
    assert output["proxy"]["name"] == "devtest"


def test_cli_adspower_create_profile_uses_selected_proxy_id(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert (
        autoproxy_cli.main(
            ["--config", str(config_path), "adspower-create-profile", "--id", "proxy-123"]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["proxy"]["id"] == "proxy-123"
    assert output["adspower_profile_id"] == "profile-7890"


def test_cli_camoufox_launch_uses_selected_proxy_id(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert (
        autoproxy_cli.main(
            [
                "--config",
                str(config_path),
                "camoufox-launch",
                "--id",
                "proxy-123",
                "--template",
                "desktop-humanized",
                "--no-wait",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["browser"] == "camoufox"
    assert output["proxy_id"] == "proxy-123"
    assert output["template_name"] == "desktop-humanized"
    assert output["proxy_server"] == "socks5://127.0.0.1:7890"


def test_cli_camoufox_templates_outputs_one_template(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert (
        autoproxy_cli.main(
            [
                "--config",
                str(config_path),
                "camoufox-templates",
                "--name",
                "desktop-humanized",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["name"] == "desktop-humanized"
    assert output["geoip"] is True


def test_cli_camoufox_profiles_outputs_selected_binding(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert (
        autoproxy_cli.main(
            ["--config", str(config_path), "camoufox-profiles", "--id", "proxy-123"]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["proxy_id"] == "proxy-123"
    assert output["local_port"] == 7890


def test_cli_run_uses_selected_proxy_id(tmp_path, monkeypatch, capsys):
    autoproxy_cli = load_cli_module()
    install_fakes(monkeypatch, autoproxy_cli)
    config_path = write_config(tmp_path)

    assert (
        autoproxy_cli.main(
            ["--config", str(config_path), "run", "--session-tag", "cli-test", "--id", "proxy-123"]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["proxy"]["id"] == "proxy-123"
    assert output["proxy"]["name"] == "by-id"


def test_selected_proxy_name_must_match_one_record(tmp_path, monkeypatch):
    autoproxy_cli = load_cli_module()
    config_path = write_config(tmp_path)

    class EmptySource(FakeProxySource):
        def find_proxies_by_name(self, name):
            return []

    monkeypatch.setattr(autoproxy_cli, "build_proxy_source", lambda config: EmptySource())

    try:
        autoproxy_cli.load_selected_proxy({"proxy_source": {}}, "missing", None)
    except ValueError as exc:
        assert "no OpenBao proxy matched name" in str(exc)
    else:
        raise AssertionError("expected ValueError")


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
