# Camoufox Adapter Design

## Context

AutoProxy currently moves one OpenBao proxy record through sub2api and Clash Verge, then creates an AdsPower browser profile that uses the Clash local SOCKS listener. The Camoufox integration should reuse the same proxy chain instead of sending Camoufox directly to the upstream proxy.

The selected approach is a local launch adapter. AutoProxy will start Camoufox through its Python interface, create or reuse a persistent local profile directory, and open BrowserScan by default so the user can inspect the resulting fingerprint and proxy state.

## Goals

- Add Camoufox as an optional browser adapter alongside AdsPower.
- Keep Clash as the browser-facing proxy boundary.
- Launch Camoufox locally with a stable persistent profile per proxy.
- Open `https://www.browserscan.net` by default when launching a profile.
- Provide query subcommands for local Camoufox templates and proxy/profile bindings.
- Keep Camoufox dependencies optional so existing workflows keep working without browser downloads.

## Non-Goals

- Do not replace sub2api or Clash.
- Do not implement remote websocket server mode in the first version.
- Do not add bulk launching, profile deletion, or profile cleanup in the first version.
- Do not persist or hand-edit low-level Camoufox fingerprint config beyond normal adapter options.
- Do not require Camoufox to be installed for non-Camoufox commands.

## External Interface

Camoufox is controlled through the Python package:

```python
from camoufox.sync_api import Camoufox
```

The adapter will lazy-import this package when a Camoufox command runs. If the package is missing, AutoProxy will return a clear installation message. The recommended optional dependency is:

```toml
[project.optional-dependencies]
camoufox = [
    "camoufox[geoip]>=0.4.11",
]
```

The first implementation should use the stable `camoufox` package. The newer `cloverlabs-camoufox` package can be evaluated later if newer patches are needed.

## Configuration

Add a top-level browser selector and a Camoufox section:

```json
{
  "browser": "camoufox",
  "camoufox": {
    "profiles_dir": "data/camoufox/profiles",
    "templates_dir": "data/camoufox/templates",
    "bindings_path": "data/camoufox/bindings.json",
    "headless": false,
    "geoip": true,
    "humanize": true,
    "start_url": "https://www.browserscan.net",
    "timeout": 30.0
  }
}
```

`start_url` defaults to `https://www.browserscan.net` even when omitted. Relative paths are resolved against the config file directory, matching existing config behavior.

If `browser` is absent and `adspower` exists, the current AdsPower flow stays unchanged. If `browser` is `camoufox`, the runner uses Camoufox and does not call AdsPower.

## Adapter Responsibilities

Create `autoproxy/adapters/camoufox_adapter.py` with a `CamoufoxAdapter` class.

Primary launch method:

```python
launch_with_local_proxy(record, *, local_host, local_port) -> CamoufoxLaunchResult
```

The method will:

- Resolve a profile directory using the proxy id, for example `data/camoufox/profiles/proxy-010`.
- Build a Camoufox proxy dictionary from the Clash listener, for example `{"server": "socks5://127.0.0.1:7891"}`.
- Launch Camoufox with `persistent_context=True` and `user_data_dir=<profile_dir>`.
- Pass configured values such as `headless`, `geoip`, `humanize`, and future safe pass-through options.
- Open the configured `start_url`, defaulting to `https://www.browserscan.net`.
- Persist a binding record that connects the OpenBao proxy id, local listener, profile directory, start URL, and launch timestamp.
- Return a structured result for CLI output and reports.

The adapter keeps the browser open for local inspection by running in the foreground. The CLI command blocks while Camoufox is open, and the user can stop the command with Ctrl+C when finished. A detached launch mode can be added later if there is a clear need for background browser management.

## Templates

Templates are local JSON files under `templates_dir`. They describe reusable Camoufox launch preferences, not complete fingerprint snapshots.

Example:

```json
{
  "name": "desktop-humanized",
  "headless": false,
  "geoip": true,
  "humanize": true,
  "os": ["windows", "macos"],
  "start_url": "https://www.browserscan.net"
}
```

The adapter will support listing templates and reading one template by name. Launch commands can optionally select a template. Explicit command/config values override template values.

Template scope is intentionally narrow. It should include normal Camoufox parameters such as `headless`, `geoip`, `humanize`, `os`, `locale`, `block_images`, and `start_url`. It should not encourage arbitrary low-level `config` overrides in the first version.

## Proxy/Profile Bindings

Bindings are local metadata stored in `bindings_path`. They make Camoufox usage queryable even though Camoufox itself is not a profile management service.

Each binding should include:

- `proxy_id`
- `proxy_name`
- `profile_dir`
- `local_host`
- `local_port`
- `proxy_server`
- `template_name`
- `start_url`
- `last_launched_at`

Bindings are keyed by `proxy_id`. Re-launching the same proxy updates the binding instead of creating a duplicate.

## CLI

Add launch and query subcommands:

```bash
python3 autoproxy.py camoufox-launch --id proxy-010
python3 autoproxy.py camoufox-launch --name devtest
python3 autoproxy.py camoufox-launch --id proxy-010 --template desktop-humanized
python3 autoproxy.py camoufox-templates
python3 autoproxy.py camoufox-templates --name desktop-humanized
python3 autoproxy.py camoufox-profiles
python3 autoproxy.py camoufox-profiles --id proxy-010
```

`camoufox-launch` selects a proxy the same way existing selector commands do, applies the Clash listener, prints the launch result as JSON before opening the browser page, then keeps the Camoufox context alive in the foreground.

`camoufox-templates` lists local templates or prints one template.

`camoufox-profiles` prints local proxy/profile bindings. This is the query command for "Camoufox proxy information" because the first version stores bindings locally instead of asking a Camoufox service.

## Runner Integration

`FlowRunner` should evolve from a hard-coded optional `adspower` dependency to an optional browser adapter dependency.

The first implementation can keep backward compatibility by accepting both fields:

- `adspower`: existing adapter, existing artifact fields.
- `browser_adapter`: new generic adapter for Camoufox.

When `browser` is `camoufox`, `build_runner()` passes a `CamoufoxAdapter`. When omitted, existing AdsPower behavior remains unchanged.

`RunArtifacts` can add optional fields for `browser`, `browser_profile_dir`, and `browser_start_url`. Existing AdsPower fields remain for compatibility.

## Error Handling

- Missing Camoufox package: raise a clear error with the optional install command.
- Missing browser binary: surface Camoufox's fetch requirement and mention `python3 -m camoufox fetch`.
- Missing template: raise `ValueError` with the template name and templates directory.
- Invalid template JSON: include the file path in the error.
- Missing or invalid bindings file: treat missing as empty; invalid JSON should raise a clear error.
- Clash write failure should stop before launching Camoufox.
- Keyboard interruption during foreground launch should close the Camoufox context cleanly and exit without rewriting unrelated bindings.

## Testing

Unit tests should not launch the real browser. Instead, inject a fake Camoufox factory and assert that the adapter:

- Builds `socks5://<local_host>:<local_port>`.
- Uses `persistent_context=True`.
- Uses the expected `user_data_dir`.
- Defaults `start_url` to `https://www.browserscan.net`.
- Merges template, config, and explicit values in the documented precedence.
- Writes and updates binding metadata idempotently.
- Lists templates and reads a template by name.
- Reports a clear error when Camoufox is not installed.

CLI tests should assert command routing and JSON output with fake adapters where practical.

Manual verification after implementation:

```bash
python3 -m pip install -e ".[camoufox]"
python3 -m camoufox fetch
python3 autoproxy.py camoufox-launch --id proxy-010
```

The launched browser should open `https://www.browserscan.net` through the Clash local SOCKS listener.

## Implementation Decisions

- Foreground launch is the only first-version runtime mode.
- `geoip` defaults to `true`, using Camoufox's built-in behavior. If local Clash indirection prevents correct exit-IP inference in manual testing, a later version will add explicit exit-IP lookup before launch.
- The supported first-version package is `camoufox`. `cloverlabs-camoufox` remains a later compatibility evaluation, not an implementation requirement.
