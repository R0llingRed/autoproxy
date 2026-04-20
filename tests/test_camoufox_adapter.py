import json
import warnings

from autoproxy.adapters.camoufox_adapter import CamoufoxAdapter
from autoproxy.models import ProxyRecord


class FakePage:
    def __init__(self):
        self.visited = []

    def goto(self, url, *, timeout=None):
        self.visited.append(url)


class FakeCamoufoxInstance:
    def __init__(self, pages=None):
        self.pages = pages or []
        self.closed = False
        self.waited_events = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    def wait_for_event(self, event, *, timeout=None):
        self.waited_events.append((event, timeout))


class FakeCamoufoxFactory:
    def __init__(self, instance=None):
        self.calls = []
        self.instances = []
        self.instance = instance

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        instance = self.instance or FakeCamoufoxInstance()
        self.instances.append(instance)
        return instance


class WarningCamoufoxInstance(FakeCamoufoxInstance):
    def __enter__(self):
        warnings.warn(
            "When using a proxy, it is heavily recommended that you pass `geoip=True`.",
            UserWarning,
        )
        return self


def make_record() -> ProxyRecord:
    return ProxyRecord.from_mapping(
        {
            "id": "proxy-010",
            "name": "devtest",
            "type": "socks5",
            "host": "1.2.3.4",
            "port": 1080,
        }
    )


def test_camoufox_launch_uses_local_socks_and_default_start_url(tmp_path):
    factory = FakeCamoufoxFactory()
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=tmp_path / "templates",
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=factory,
    )

    result = adapter.launch_with_local_proxy(
        make_record(),
        local_host="127.0.0.1",
        local_port=7891,
        keep_open=False,
    )

    assert result.start_url == "https://www.browserscan.net"
    assert result.proxy_server == "socks5://127.0.0.1:7891"
    assert result.profile_dir == str(tmp_path / "profiles" / "proxy-010")
    assert factory.calls[0]["proxy"] == {"server": "socks5://127.0.0.1:7891"}
    assert factory.calls[0]["persistent_context"] is True
    assert factory.calls[0]["user_data_dir"] == str(tmp_path / "profiles" / "proxy-010")
    assert factory.instances[0].pages[0].visited == ["https://www.browserscan.net"]


def test_camoufox_lists_templates_and_reads_one_by_name(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "desktop-humanized.json").write_text(
        '{"name":"desktop-humanized","headless":false,"geoip":true}',
        encoding="utf-8",
    )
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=templates,
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=FakeCamoufoxFactory(),
    )

    assert adapter.list_templates() == [
        {"name": "desktop-humanized", "headless": False, "geoip": True}
    ]
    assert adapter.get_template("desktop-humanized")["geoip"] is True


def test_camoufox_updates_binding_for_same_proxy(tmp_path):
    factory = FakeCamoufoxFactory()
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=tmp_path / "templates",
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=factory,
    )

    adapter.launch_with_local_proxy(
        make_record(),
        local_host="127.0.0.1",
        local_port=7891,
        keep_open=False,
    )
    adapter.launch_with_local_proxy(
        make_record(),
        local_host="127.0.0.1",
        local_port=7892,
        keep_open=False,
    )

    bindings = adapter.list_bindings()
    assert len(bindings) == 1
    assert bindings[0]["proxy_id"] == "proxy-010"
    assert bindings[0]["proxy_name"] == "devtest"
    assert bindings[0]["local_port"] == 7892
    assert bindings[0]["start_url"] == "https://www.browserscan.net"
    assert json.loads((tmp_path / "bindings.json").read_text(encoding="utf-8"))[
        "proxy-010"
    ]["local_port"] == 7892


def test_camoufox_template_values_override_builtin_defaults(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "headless-template.json").write_text(
        json.dumps(
            {
                "name": "headless-template",
                "headless": True,
                "geoip": False,
                "humanize": False,
            }
        ),
        encoding="utf-8",
    )
    factory = FakeCamoufoxFactory()
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=templates,
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=factory,
    )

    adapter.launch_with_local_proxy(
        make_record(),
        local_host="127.0.0.1",
        local_port=7891,
        template_name="headless-template",
        keep_open=False,
    )

    assert factory.calls[0]["headless"] is True
    assert factory.calls[0]["geoip"] is False
    assert factory.calls[0]["humanize"] is False


def test_camoufox_disables_geoip_before_launching_through_local_proxy(tmp_path):
    factory = FakeCamoufoxFactory()
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=tmp_path / "templates",
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=factory,
    )

    adapter.launch_with_local_proxy(
        make_record(),
        local_host="127.0.0.1",
        local_port=7891,
        keep_open=False,
    )

    assert len(factory.calls) == 1
    assert factory.calls[0]["geoip"] is False
    assert factory.calls[0]["proxy"] == {"server": "socks5://127.0.0.1:7891"}
    assert factory.instances[0].pages[0].visited == ["https://www.browserscan.net"]


def test_camoufox_reuses_existing_page_and_waits_for_context_close(tmp_path):
    initial_page = FakePage()
    instance = FakeCamoufoxInstance(pages=[initial_page])
    factory = FakeCamoufoxFactory(instance=instance)
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=tmp_path / "templates",
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=factory,
    )

    adapter.launch_with_local_proxy(
        make_record(),
        local_host="127.0.0.1",
        local_port=7891,
        keep_open=True,
    )

    assert instance.pages == [initial_page]
    assert initial_page.visited == ["https://www.browserscan.net"]
    assert instance.waited_events == [("close", 0)]


def test_camoufox_suppresses_expected_geoip_warning_for_local_proxy(tmp_path, recwarn):
    instance = WarningCamoufoxInstance()
    factory = FakeCamoufoxFactory(instance=instance)
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=tmp_path / "templates",
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=factory,
    )

    adapter.launch_with_local_proxy(
        make_record(),
        local_host="127.0.0.1",
        local_port=7891,
        keep_open=False,
    )

    assert list(recwarn) == []
