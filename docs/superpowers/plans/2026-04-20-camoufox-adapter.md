# Camoufox Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AutoProxy 增加本地启动型 Camoufox 浏览器适配器，支持默认打开 BrowserScan，并查询本地模板和代理/profile 绑定信息。

**Architecture:** 新增 `CamoufoxAdapter` 管理本地模板、bindings 文件和 Camoufox 启动参数。CLI 增加 `camoufox-launch`、`camoufox-templates`、`camoufox-profiles` 子命令，runner 通过 `browser=camoufox` 选择新 browser adapter，同时保留 AdsPower 旧行为。

**Tech Stack:** Python 3.11+、pytest、requests、PyYAML、可选依赖 `camoufox[geoip]`。

---

## 文件结构

- 新建 `autoproxy/adapters/camoufox_adapter.py`：Camoufox 配置合并、模板读取、bindings 读写、启动参数组装和本地启动。
- 修改 `autoproxy/models.py`：给运行报告增加通用 browser 字段，保持 AdsPower 字段兼容。
- 修改 `autoproxy/runner.py`：支持 `browser_adapter`，当配置选择 Camoufox 时调用新 adapter。
- 修改 `autoproxy.py`：构造 Camoufox adapter，增加三个 Camoufox 子命令。
- 修改 `autoproxy/adapters/__init__.py`：导出新 adapter。
- 修改 `pyproject.toml`：增加 `camoufox` 可选依赖。
- 修改 `config.openbao.example.json`：增加 `browser` 和 `camoufox` 示例配置。
- 修改 `README.md`：用中文补充 Camoufox 安装、启动和查询命令。
- 新建 `tests/test_camoufox_adapter.py`：覆盖 adapter 行为。
- 修改 `tests/test_cli.py` 和 `tests/test_runner.py`：覆盖 CLI 与 runner 集成。

## Task 1: Adapter 基础能力

**Files:**
- Create: `autoproxy/adapters/camoufox_adapter.py`
- Test: `tests/test_camoufox_adapter.py`

- [ ] **Step 1: 写失败测试**

```python
def test_camoufox_launch_uses_local_socks_and_default_start_url(tmp_path):
    factory = FakeCamoufoxFactory()
    adapter = CamoufoxAdapter(
        profiles_dir=tmp_path / "profiles",
        templates_dir=tmp_path / "templates",
        bindings_path=tmp_path / "bindings.json",
        camoufox_factory=factory,
    )
    record = ProxyRecord.from_mapping({"id": "proxy-010", "name": "devtest", "type": "socks5", "host": "1.2.3.4", "port": 1080})

    result = adapter.launch_with_local_proxy(record, local_host="127.0.0.1", local_port=7891, keep_open=False)

    assert result.start_url == "https://www.browserscan.net"
    assert result.proxy_server == "socks5://127.0.0.1:7891"
    assert factory.calls[0]["proxy"] == {"server": "socks5://127.0.0.1:7891"}
    assert factory.calls[0]["persistent_context"] is True
    assert factory.calls[0]["user_data_dir"] == str(tmp_path / "profiles" / "proxy-010")
    assert factory.instances[0].pages[0].visited == ["https://www.browserscan.net"]
```

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_camoufox_adapter.py::test_camoufox_launch_uses_local_socks_and_default_start_url -v`

Expected: FAIL，因为 `autoproxy.adapters.camoufox_adapter` 尚不存在。

- [ ] **Step 3: 写最小实现**

实现 `CamoufoxLaunchResult`、`CamoufoxAdapter.launch_with_local_proxy()`、默认 `start_url`、profile 目录和 `proxy` 参数组装。

- [ ] **Step 4: 验证测试通过**

Run: `pytest tests/test_camoufox_adapter.py::test_camoufox_launch_uses_local_socks_and_default_start_url -v`

Expected: PASS。

## Task 2: 模板与 bindings 查询

**Files:**
- Modify: `autoproxy/adapters/camoufox_adapter.py`
- Test: `tests/test_camoufox_adapter.py`

- [ ] **Step 1: 写失败测试**

新增测试覆盖：

```python
def test_camoufox_lists_templates_and_reads_one_by_name(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "desktop-humanized.json").write_text('{"name":"desktop-humanized","headless":false,"geoip":true}', encoding="utf-8")
    adapter = CamoufoxAdapter(profiles_dir=tmp_path / "profiles", templates_dir=templates, bindings_path=tmp_path / "bindings.json", camoufox_factory=FakeCamoufoxFactory())

    assert adapter.list_templates() == [{"name": "desktop-humanized", "headless": False, "geoip": True}]
    assert adapter.get_template("desktop-humanized")["geoip"] is True


def test_camoufox_updates_binding_for_same_proxy(tmp_path):
    factory = FakeCamoufoxFactory()
    adapter = CamoufoxAdapter(profiles_dir=tmp_path / "profiles", templates_dir=tmp_path / "templates", bindings_path=tmp_path / "bindings.json", camoufox_factory=factory)
    record = ProxyRecord.from_mapping({"id": "proxy-010", "name": "devtest", "type": "socks5", "host": "1.2.3.4", "port": 1080})

    adapter.launch_with_local_proxy(record, local_host="127.0.0.1", local_port=7891, keep_open=False)
    adapter.launch_with_local_proxy(record, local_host="127.0.0.1", local_port=7892, keep_open=False)

    bindings = adapter.list_bindings()
    assert len(bindings) == 1
    assert bindings[0]["proxy_id"] == "proxy-010"
    assert bindings[0]["local_port"] == 7892
```

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_camoufox_adapter.py -v`

Expected: FAIL，因为模板和 bindings 方法尚未实现。

- [ ] **Step 3: 写最小实现**

实现 `list_templates()`、`get_template()`、`list_bindings()`、`get_binding()` 和 bindings JSON 原子更新。

- [ ] **Step 4: 验证测试通过**

Run: `pytest tests/test_camoufox_adapter.py -v`

Expected: PASS。

## Task 3: CLI 集成

**Files:**
- Modify: `autoproxy.py`
- Modify: `autoproxy/adapters/__init__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

新增 CLI 测试，使用 monkeypatch 替换 builder，覆盖 `camoufox-templates`、`camoufox-profiles`、`camoufox-launch` 输出 JSON。

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_cli.py -v`

Expected: FAIL，因为 CLI 子命令尚不存在。

- [ ] **Step 3: 写最小实现**

实现 `build_camoufox()`、三个命令 handler、parser 注册和 selector 参数。

- [ ] **Step 4: 验证测试通过**

Run: `pytest tests/test_cli.py -v`

Expected: PASS。

## Task 4: Runner 和模型集成

**Files:**
- Modify: `autoproxy/models.py`
- Modify: `autoproxy/runner.py`
- Modify: `autoproxy.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: 写失败测试**

新增 runner 测试，断言 `browser_adapter.launch_with_local_proxy()` 收到 Clash listener，artifact 包含 `browser="camoufox"`、profile dir 和 start URL。

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_runner.py -v`

Expected: FAIL，因为 runner 尚未支持 `browser_adapter`。

- [ ] **Step 3: 写最小实现**

给 `FlowRunner` 增加 `browser_adapter`，给 `RunArtifacts` 增加可选 browser 字段，`build_runner()` 根据 `browser` 配置选择 AdsPower 或 Camoufox。

- [ ] **Step 4: 验证测试通过**

Run: `pytest tests/test_runner.py -v`

Expected: PASS。

## Task 5: 配置、依赖和中文文档

**Files:**
- Modify: `pyproject.toml`
- Modify: `config.openbao.example.json`
- Modify: `README.md`

- [ ] **Step 1: 写/更新验证**

Run: `pytest -q`

Expected: 通过现有自动化测试，确认配置和依赖变更没有破坏导入。

- [ ] **Step 2: 修改文档和配置**

增加可选依赖 `camoufox`，示例配置增加 `browser` 和 `camoufox` 字段，README 用中文补充安装、启动、查询命令。

- [ ] **Step 3: 全量验证**

Run: `pytest`

Expected: 全部测试通过。

## 自审

- 设计中的默认 BrowserScan、模板查询、代理/profile bindings 查询、可选依赖、runner 兼容 AdsPower 都有对应任务。
- 计划不包含 TBD/TODO/FIXME。
- 方法名统一使用 `launch_with_local_proxy()`、`list_templates()`、`get_template()`、`list_bindings()`、`get_binding()`。
