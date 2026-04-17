from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from autoproxy.adapters.adspower_adapter import AdsPowerAdapter
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


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        if env_name not in os.environ:
            raise ValueError(f"required environment variable {env_name!r} is not set")
        return os.environ[env_name]
    if isinstance(value, dict):
        return {key: _resolve_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env(item) for item in value]
    return value


def load_config(path: Path) -> dict[str, Any]:
    return _resolve_env(json.loads(path.read_text()))


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
            return TxtProxySource(path=Path(source["path"]).expanduser())
        if source_type == "openbao":
            return OpenBaoProxySource(
                base_url=source["base_url"],
                token=source["token"],
                mount=source.get("mount", "secret"),
                secret_path=source["secret_path"],
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
        managed_group_name=clash.get("managed_group_name", "AUTO-CHAIN"),
        managed_proxy_prefix=clash.get("managed_proxy_prefix", "auto-chain-"),
        listener_start_port=clash.get("listener_start_port", 7890),
        listener_host=clash.get("listener_host", "127.0.0.1"),
        config_path=Path(clash["config_path"]).expanduser(),
    )


def build_adspower(config: dict[str, Any]) -> AdsPowerAdapter | None:
    if "adspower" not in config:
        return None
    return AdsPowerAdapter(**config["adspower"])


def build_runner(config: dict[str, Any]) -> FlowRunner:
    return FlowRunner(
        proxy_source=build_proxy_source(config),
        sub2api=build_sub2api(config),
        clash=build_clash(config),
        report_base_dir=Path(config["report_base_dir"]).expanduser(),
        adspower=build_adspower(config),
    )


def load_proxy(config: dict[str, Any]) -> ProxyRecord:
    return ProxyRecord.from_mapping(build_proxy_source(config).fetch_proxy())


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_openbao_get(config: dict[str, Any], _args: argparse.Namespace) -> int:
    print_json(load_proxy(config).to_dict())
    return 0


def cmd_openbao_import(config: dict[str, Any], args: argparse.Namespace) -> int:
    source = build_proxy_source(config)
    if not hasattr(source, "write_proxies_from_file"):
        raise ValueError("configured proxy source does not support file import")
    written = source.write_proxies_from_file(Path(args.file).expanduser())
    print_json({"written": written})
    return 0


def cmd_sub2api_sync(config: dict[str, Any], _args: argparse.Namespace) -> int:
    record = load_proxy(config)
    proxy_id = build_sub2api(config).sync_proxy(record)
    print_json({"sub2api_proxy_id": proxy_id, "proxy": record.to_dict()})
    return 0


def cmd_clash_write(config: dict[str, Any], _args: argparse.Namespace) -> int:
    record = load_proxy(config)
    result = build_clash(config).apply_proxy(record)
    print_json(
        {
            "node_name": result.node_name,
            "listener_name": result.listener_name,
            "local_host": result.local_host,
            "local_port": result.local_port,
            "proxy": record.to_dict(),
        }
    )
    return 0


def cmd_adspower_add_proxy(config: dict[str, Any], _args: argparse.Namespace) -> int:
    adspower = build_adspower(config)
    if adspower is None:
        raise ValueError("config does not define adspower")
    record = load_proxy(config)
    proxy_id = adspower.add_proxy(record)
    print_json({"adspower_proxy_id": proxy_id, "proxy": record.to_dict()})
    return 0


def cmd_adspower_create_profile(config: dict[str, Any], _args: argparse.Namespace) -> int:
    adspower = build_adspower(config)
    if adspower is None:
        raise ValueError("config does not define adspower")
    record = load_proxy(config)
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
            "proxy": record.to_dict(),
        }
    )
    return 0


def cmd_run(config: dict[str, Any], args: argparse.Namespace) -> int:
    artifacts = build_runner(config).run(session_tag=args.session_tag)
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
        "openbao-import": cmd_openbao_import,
        "sub2api-sync": cmd_sub2api_sync,
        "clash-write": cmd_clash_write,
        "adspower-add-proxy": cmd_adspower_add_proxy,
        "adspower-create-profile": cmd_adspower_create_profile,
        "run": cmd_run,
    }
    for name, handler in command_handlers.items():
        subparser = subcommands.add_parser(name)
        subparser.set_defaults(handler=handler)
        if name == "openbao-import":
            subparser.add_argument("--file", required=True, help="Path to proxy JSON file.")
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
