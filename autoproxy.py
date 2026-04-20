from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from autoproxy.adapters.adspower_adapter import AdsPowerAdapter
from autoproxy.adapters.camoufox_adapter import CamoufoxAdapter
from autoproxy.adapters.clash_adapter import ClashVergeAdapter
from autoproxy.adapters.openbao_source import OpenBaoProxySource
from autoproxy.adapters.sub2api_adapter import Sub2ApiAdapter
from autoproxy.adapters.txt_source import TxtProxySource
from autoproxy.models import ProxyRecord
from autoproxy.runner import FlowRunner


DEFAULT_CONFIG_PATHS = [
    Path("config.local.json"),
    Path("config.openbao.json"),
    Path("config.openbao.example.json"),
]
CONFIG_DIR_KEY = "__config_dir"
ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            env_name = match.group(1)
            default = match.group(2)
            if env_name not in os.environ:
                if default is not None:
                    return default
                raise ValueError(f"required environment variable {env_name!r} is not set")
            return os.environ[env_name]

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _resolve_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env(item) for item in value]
    return value


def load_config(path: Path) -> dict[str, Any]:
    resolved_path = path.expanduser().resolve()
    config = _resolve_env(json.loads(resolved_path.read_text(encoding="utf-8")))
    config[CONFIG_DIR_KEY] = resolved_path.parent
    return config


def resolve_path(value: str | Path, config: dict[str, Any]) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return Path(config.get(CONFIG_DIR_KEY, Path.cwd())) / path


def resolve_config_path(path: str | None) -> Path:
    if path:
        return Path(path)
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate
    joined = ", ".join(str(candidate) for candidate in DEFAULT_CONFIG_PATHS)
    raise FileNotFoundError(f"no config file found; checked: {joined}")


def build_proxy_source(config: dict[str, Any]):
    source = config.get("proxy_source")
    if source:
        source_type = source["type"]
        if source_type == "txt":
            return TxtProxySource(path=resolve_path(source["path"], config))
        if source_type == "openbao":
            return OpenBaoProxySource(
                base_url=source["base_url"],
                token=source["token"],
                mount=source.get("mount", "secret"),
                read_path=source.get("read_path"),
                import_prefix=source.get("import_prefix"),
                secret_path=source.get("secret_path"),
                timeout=source.get("timeout", 10.0),
            )
        raise ValueError(f"unsupported proxy_source type: {source_type}")
    raise ValueError("config must define proxy_source")


def build_sub2api(config: dict[str, Any]) -> Sub2ApiAdapter:
    return Sub2ApiAdapter(**config["sub2api"])


def build_clash(config: dict[str, Any]) -> ClashVergeAdapter:
    clash = config["clash"]
    return ClashVergeAdapter(
        base_proxy_name=clash.get("base_proxy_name", "A"),
        write_mode=clash.get("write_mode", "yaml"),
        managed_group_name=clash.get("managed_group_name", "AUTO-CHAIN"),
        managed_proxy_prefix=clash.get("managed_proxy_prefix", "auto-chain-"),
        listener_start_port=clash.get("listener_start_port", 7890),
        listener_host=clash.get("listener_host", "127.0.0.1"),
        config_path=resolve_path(clash["config_path"], config) if clash.get("config_path") else None,
        script_path=resolve_path(clash["script_path"], config) if clash.get("script_path") else None,
        profiles_path=resolve_path(clash["profiles_path"], config) if clash.get("profiles_path") else None,
        profile_dir=resolve_path(clash["profile_dir"], config) if clash.get("profile_dir") else None,
        reload_after_write=clash.get("reload_after_write", False),
        controller_url=clash.get("controller_url"),
        controller_secret=clash.get("controller_secret"),
        reload_force=clash.get("reload_force", True),
        timeout=clash.get("timeout", 10.0),
    )


def build_adspower(config: dict[str, Any]) -> AdsPowerAdapter | None:
    if "adspower" not in config:
        return None
    return AdsPowerAdapter(**config["adspower"])


def build_camoufox(config: dict[str, Any]) -> CamoufoxAdapter:
    camoufox = config.get("camoufox", {})
    return CamoufoxAdapter(
        profiles_dir=resolve_path(camoufox.get("profiles_dir", "data/camoufox/profiles"), config),
        templates_dir=resolve_path(camoufox.get("templates_dir", "data/camoufox/templates"), config),
        bindings_path=resolve_path(camoufox.get("bindings_path", "data/camoufox/bindings.json"), config),
        headless=camoufox.get("headless"),
        geoip=camoufox.get("geoip"),
        humanize=camoufox.get("humanize"),
        start_url=camoufox.get("start_url"),
        timeout=camoufox.get("timeout", 30.0),
        os=camoufox.get("os"),
        locale=camoufox.get("locale"),
        block_images=camoufox.get("block_images"),
    )


def build_runner(config: dict[str, Any]) -> FlowRunner:
    browser = config.get("browser")
    adspower = build_adspower(config)
    browser_adapter = None
    if browser == "camoufox":
        adspower = None
        browser_adapter = build_camoufox(config)
    elif browser not in {None, "adspower"}:
        raise ValueError(f"unsupported browser: {browser}")
    return FlowRunner(
        proxy_source=build_proxy_source(config),
        sub2api=build_sub2api(config),
        clash=build_clash(config),
        report_base_dir=resolve_path(config["report_base_dir"], config),
        adspower=adspower,
        browser_adapter=browser_adapter,
    )


class StaticProxySource:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def fetch_proxy(self) -> dict[str, Any]:
        return dict(self.payload)


def load_selected_proxy(
    config: dict[str, Any],
    name: str | None,
    proxy_id: str | None,
) -> ProxyRecord:
    source = build_proxy_source(config)
    if proxy_id:
        return ProxyRecord.from_mapping(source.fetch_proxy_by_id(proxy_id))
    if name:
        matches = source.find_proxies_by_name(name)
        if not matches:
            raise ValueError(f"no OpenBao proxy matched name {name!r}")
        if len(matches) > 1:
            ids = ", ".join(str(item.get("id")) for item in matches)
            raise ValueError(f"multiple OpenBao proxies matched name {name!r}: {ids}")
        return ProxyRecord.from_mapping(matches[0])
    return ProxyRecord.from_mapping(source.fetch_proxy())


def load_proxy(config: dict[str, Any]) -> ProxyRecord:
    return ProxyRecord.from_mapping(build_proxy_source(config).fetch_proxy())


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_openbao_get(config: dict[str, Any], args: argparse.Namespace) -> int:
    source = build_proxy_source(config)
    if args.id:
        print_json(ProxyRecord.from_mapping(source.fetch_proxy_by_id(args.id)).to_dict())
        return 0
    if args.name:
        print_json(
            [
                ProxyRecord.from_mapping(item).to_dict()
                for item in source.find_proxies_by_name(args.name)
            ]
        )
        return 0
    print_json([ProxyRecord.from_mapping(item).to_dict() for item in source.fetch_all_proxies()])
    return 0


def cmd_openbao_grep(config: dict[str, Any], args: argparse.Namespace) -> int:
    source = build_proxy_source(config)
    print_json(
        [
            ProxyRecord.from_mapping(item).to_dict()
            for item in source.grep_proxies(args.keyword)
        ]
    )
    return 0


def cmd_openbao_import(config: dict[str, Any], args: argparse.Namespace) -> int:
    source = build_proxy_source(config)
    if not hasattr(source, "write_proxies_from_file"):
        raise ValueError("configured proxy source does not support file import")
    written = source.write_proxies_from_file(Path(args.file).expanduser())
    print_json({"written": written})
    return 0


def cmd_sub2api_sync(config: dict[str, Any], args: argparse.Namespace) -> int:
    record = load_selected_proxy(config, args.name, args.id)
    proxy_id = build_sub2api(config).sync_proxy(record)
    print_json({"sub2api_proxy_id": proxy_id, "proxy": record.to_dict()})
    return 0


def cmd_clash_write(config: dict[str, Any], args: argparse.Namespace) -> int:
    record = load_selected_proxy(config, args.name, args.id)
    result = build_clash(config).apply_proxy(record)
    print_json(
        {
            "node_name": result.node_name,
            "listener_name": result.listener_name,
            "local_host": result.local_host,
            "local_port": result.local_port,
            "reload_status": getattr(result, "reload_status", "skipped"),
            "proxy": record.to_dict(),
        }
    )
    return 0


def cmd_adspower_add_proxy(config: dict[str, Any], args: argparse.Namespace) -> int:
    adspower = build_adspower(config)
    if adspower is None:
        raise ValueError("config does not define adspower")
    record = load_selected_proxy(config, args.name, args.id)
    proxy_id = adspower.add_proxy(record)
    print_json({"adspower_proxy_id": proxy_id, "proxy": record.to_dict()})
    return 0


def cmd_adspower_create_profile(config: dict[str, Any], args: argparse.Namespace) -> int:
    adspower = build_adspower(config)
    if adspower is None:
        raise ValueError("config does not define adspower")
    record = load_selected_proxy(config, args.name, args.id)
    clash_result = build_clash(config).apply_proxy(record)
    profile_id = adspower.create_profile_with_local_proxy(
        record,
        local_host=clash_result.local_host,
        local_port=clash_result.local_port,
    )
    print_json(
        {
            "adspower_profile_id": profile_id,
            "local_host": clash_result.local_host,
            "local_port": clash_result.local_port,
            "reload_status": getattr(clash_result, "reload_status", "skipped"),
            "proxy": record.to_dict(),
        }
    )
    return 0


def cmd_camoufox_launch(config: dict[str, Any], args: argparse.Namespace) -> int:
    record = load_selected_proxy(config, args.name, args.id)
    clash_result = build_clash(config).apply_proxy(record)
    result = build_camoufox(config).launch_with_local_proxy(
        record,
        local_host=clash_result.local_host,
        local_port=clash_result.local_port,
        template_name=args.template,
        keep_open=not args.no_wait,
    )
    print_json(result.to_dict())
    return 0


def cmd_camoufox_templates(config: dict[str, Any], args: argparse.Namespace) -> int:
    camoufox = build_camoufox(config)
    if args.name:
        print_json(camoufox.get_template(args.name))
    else:
        print_json(camoufox.list_templates())
    return 0


def cmd_camoufox_profiles(config: dict[str, Any], args: argparse.Namespace) -> int:
    camoufox = build_camoufox(config)
    if args.id:
        print_json(camoufox.get_binding(args.id))
    else:
        print_json(camoufox.list_bindings())
    return 0


def cmd_run(config: dict[str, Any], args: argparse.Namespace) -> int:
    runner = build_runner(config)
    if args.id or args.name:
        runner.proxy_source = StaticProxySource(
            load_selected_proxy(config, args.name, args.id).to_dict()
        )
    artifacts = runner.run(session_tag=args.session_tag)
    print_json(artifacts.to_dict())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AutoProxy module runner.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the JSON config file. Defaults to config.local.json when present.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    command_handlers = {
        "openbao-get": cmd_openbao_get,
        "openbao-grep": cmd_openbao_grep,
        "openbao-import": cmd_openbao_import,
        "sub2api-sync": cmd_sub2api_sync,
        "clash-write": cmd_clash_write,
        "adspower-add-proxy": cmd_adspower_add_proxy,
        "adspower-create-profile": cmd_adspower_create_profile,
        "camoufox-launch": cmd_camoufox_launch,
        "camoufox-templates": cmd_camoufox_templates,
        "camoufox-profiles": cmd_camoufox_profiles,
        "run": cmd_run,
    }
    selector_commands = {
        "sub2api-sync",
        "clash-write",
        "adspower-add-proxy",
        "adspower-create-profile",
        "camoufox-launch",
        "run",
    }
    for name, handler in command_handlers.items():
        subparser = subcommands.add_parser(name)
        subparser.set_defaults(handler=handler)
        if name == "openbao-get":
            group = subparser.add_mutually_exclusive_group()
            group.add_argument("--id", help="Read one OpenBao proxy by id under import_prefix.")
            group.add_argument("--name", help="Read OpenBao proxies whose name matches exactly.")
        if name == "openbao-grep":
            subparser.add_argument("keyword", help="Search all OpenBao proxy fields under import_prefix.")
        if name in selector_commands:
            group = subparser.add_mutually_exclusive_group()
            group.add_argument("--id", help="Select one OpenBao proxy by id under import_prefix.")
            group.add_argument("--name", help="Select one OpenBao proxy whose name matches exactly.")
        if name == "openbao-import":
            subparser.add_argument("--file", required=True, help="Path to proxy JSON file.")
        if name == "camoufox-launch":
            subparser.add_argument("--template", help="Use a Camoufox template by name.")
            subparser.add_argument(
                "--no-wait",
                action="store_true",
                help="Launch and close immediately after opening start_url; intended for tests.",
            )
        if name == "camoufox-templates":
            subparser.add_argument("--name", help="Read one Camoufox template by name.")
        if name == "camoufox-profiles":
            subparser.add_argument("--id", help="Read one Camoufox binding by proxy id.")
        if name == "run":
            subparser.add_argument("--session-tag", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(resolve_config_path(args.config))
    return args.handler(config, args)


if __name__ == "__main__":
    raise SystemExit(main())
