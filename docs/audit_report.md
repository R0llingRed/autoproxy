# AutoProxy 代码审计报告

## 1. Bug 与潜在风险

### 🔴 严重：`_write_config_atomic` 中临时文件在异常时泄露

**文件**: `clash_adapter.py` L157–166

```python
with NamedTemporaryFile("w", encoding="utf-8", dir=..., delete=False) as handle:
    handle.write(content)
    temp_path = Path(handle.name)
yaml.safe_load(temp_path.read_text())   # ← 若此行抛异常，temp_path 永久残留
os.replace(temp_path, self.config_path)
```

问题：`delete=False` + YAML 二次解析失败时，临时文件不会被清理。

**建议修复**：
```python
with NamedTemporaryFile("w", encoding="utf-8", dir=self.config_path.parent, delete=False) as fh:
    fh.write(content)
    temp_path = Path(fh.name)
try:
    yaml.safe_load(temp_path.read_text())   # 验证
    os.replace(temp_path, self.config_path)
except Exception:
    temp_path.unlink(missing_ok=True)
    raise
```

---

### 🔴 严重：`Sub2ApiAdapter` 使用 `dataclass` 但修改了字段 `self.token`

**文件**: `sub2api_adapter.py` L73

```python
self.token = token  # dataclass(slots=True) 的字段被就地篡改
```

`slots=True` 的 dataclass 是允许赋值的，但语义上这是"首次 login 后把副作用缓存进 self"，行为与不可变 dataclass 割裂。次级问题：`login()` 被 `sync_proxy()` 和 `list_proxies()` 各调用一次，流程中只有一次有效调用，但如果 token 过期靠外层重新构造才能刷新——缺少显式的 token 刷新或过期处理机制。

**建议**：将 `token` 提取为内部 `_token: str | None` 缓存字段（或去掉 slots 改用普通 dataclass 并加注释说明其有状态）。

---

### 🟡 中：`find_proxy` / `find_profile` 只翻第一页(200条)，存在漏判重复的风险

**文件**: `adspower_adapter.py` L54, `sub2api_adapter.py` L33–38

AdsPower 查重时：`{"page": "1", "limit": "200"}`，Sub2Api 查重时：`{"page_size": 20}`。若代理数量超出阈值，已有的代理记录不会被查到，导致重复创建。

**建议**：增加分页遍历逻辑，或在文档/注释中明确说明这是有意的简化假设，并标注最大承载量。

---

### 🟡 中：`AdsPowerAdapter.session` 字段类型为 `Any = requests`

**文件**: `adspower_adapter.py` L16, `openbao_source.py` L18, `sub2api_adapter.py` L22

三个 Adapter 都用了 `session: Any = requests` 这种"模块当 session 对象用"的模式。虽然能工作，但：

1. `requests` 模块级别没有连接池复用（每次请求新建 TCP 连接）。
2. 类型标注 `Any` 使静态分析无法保护接口契约。
3. 测试中 `FakeSession` 已经符合 `requests.Session` 鸭子协议，完全可以标注为 `Protocol`。

**建议**：生产用途下注入 `requests.Session()`（享受连接池），并定义一个 `HttpSession(Protocol)` 类型。

---

### 🟡 中：`_resolve_env` 不支持嵌套 `list[dict]`

**文件**: `autoproxy.py` L26–27

```python
if isinstance(value, list):
    return [_resolve_env(item) for item in value]
```

只展开了 list 的第一层；如果配置中出现 `list[dict]`（虽然当前配置没有），内层 dict 里的 `${VAR}` 不会被展开。此处逻辑已是递归，问题不大，但代码注释缺失——读者不容易看出这是深度递归而非浅层替换。

---

### 🟢 轻微：`Reporter.write_run_report` 返回值从未被消费

**文件**: `runner.py` L53

```python
Reporter(base_dir=self.report_base_dir).write_run_report(artifacts)
```

`write_run_report` 返回 `dict[str, Path]`，但调用方直接丢弃。若日后想把报告路径附在 artifacts 里，会需要修改两处。

**建议**：要么让 `write_run_report` 返回 `None`，要么在 `FlowRunner.run` 里用这个返回值。

---

## 2. 架构与设计问题

### ⚡ `autoproxy.py` 既是入口脚本又承担工厂职责

文件有 203 行，包含：CLI 解析、配置加载、`build_*` 工厂函数、命令回调函数。随着命令增多，这个文件会成为"垃圾堆"。

**建议**：将 `build_*` 工厂拆入 `autoproxy/factory.py`，命令回调拆入 `autoproxy/commands.py`，`autoproxy.py` 只保留 `main()` 入口。

---

### ⚡ `FlowRunner` 中 ValidationResult 是硬编码的占位符

**文件**: `runner.py` L33–42

```python
validation = ValidationResult(
    status="SKIPPED",
    stage="browser_validation_not_run",
    reasons=["adspower_profile_created_without_browser_start"],
    ...
)
```

整个 `ValidationResult` 是写死的"跳过"状态，没有任何实际验证逻辑。这说明 `models.py` 里的 `ValidationResult` 和 `RunArtifacts.screenshots` 字段目前是"设计洞"（未实现的功能槽），但没有任何注释或 TODO 标记。

**建议**：在代码里加 `# TODO: implement browser validation` 注释，或从 `RunArtifacts` 中暂时删去这些字段，待实际实现再补回。

---

### ⚡ `build_proxy_source` 用 `if/elif` 字符串分发，可扩展性差

**文件**: `autoproxy.py` L36–50

```python
if source_type == "txt":
    return TxtProxySource(...)
if source_type == "openbao":
    return OpenBaoProxySource(...)
raise ValueError(...)
```

每增加一个 source 需要修改这个函数（违反开闭原则）。

**建议**：用注册表 dict 代替：
```python
_SOURCE_REGISTRY: dict[str, type] = {
    "txt": TxtProxySource,
    "openbao": OpenBaoProxySource,
}

def build_proxy_source(config):
    source = config["proxy_source"]
    cls = _SOURCE_REGISTRY.get(source["type"])
    if cls is None:
        raise ValueError(f"unsupported proxy_source type: {source['type']}")
    ...
```

---

### ⚡ `cmd_openbao_import` 用 `hasattr` 检测能力，违反类型约定

**文件**: `autoproxy.py` L100

```python
if not hasattr(source, "write_proxies_from_file"):
    raise ValueError("configured proxy source does not support file import")
```

应该定义一个 `Protocol` 或基类来区分"只读 source"和"可写 source"，而不是运行时 duck-type 检查。

---

### ⚡ 没有 Protocol / ABC 约束 Adapter 接口

`FlowRunner` 中：
```python
proxy_source: Any
sub2api: Any
clash: Any
adspower: Any | None
```

全是 `Any`，静态类型无法保护。若接口改动，测试能抓到，但编辑器无法给出提示。

**建议**：在 `autoproxy/adapters/__init__.py` 中定义 `ProxySource(Protocol)`, `Sub2ApiPort(Protocol)`, `ClashPort(Protocol)`, `AdsPowerPort(Protocol)` 四个协议类，`FlowRunner` 字段用这些类型。

---

## 3. 代码精简机会

### 💡 `ProxyRecord.from_mapping` 中下半段可以复用 `from_uri`

```python
# 当前：当 raw_uri 不存在时，走手动构建路径（约12行）
return cls(
    id=payload["id"],
    name=payload.get("name"),
    type=payload["type"],
    ...
)
```

事实上，若能保证 `payload` 里字段完整，直接 `cls(**{...})` 或写一个内部 `_from_fields` 更清晰。现在这段逻辑和 `from_uri` 高度镜像。

---

### 💡 `_write_config_atomic` 中 `config_path is None` 的重复保护

```python
def apply_proxy(self, record):
    if self.config_path is None:           # 第一道判断
        return ClashApplyResult(...)
    ...
    self._write_config_atomic(updated)

def _write_config_atomic(self, content):
    if self.config_path is None:           # 第二道判断（冗余）
        return
```

第二个判断是防御性代码，但因为 `apply_proxy` 已经保护过，实际上永远不会触发。可以加断言替代：`assert self.config_path is not None`，让错误更显眼。

---

### 💡 `adspower_adapter.py` 中 `base_url.rstrip('/')` 重复 4 次

每次 API 调用都有 `f"{self.base_url.rstrip('/')}/..."` 的模式。建议：
```python
@property
def _base(self) -> str:
    return self.base_url.rstrip("/")
```
`openbao_source.py` 和 `sub2api_adapter.py` 也有类似问题（各重复2次）。

---

### 💡 `Reporter._render_markdown` 用 list.append 拼字符串，可改用 `textwrap.dedent` + f-string 模板

当前代码有约 15 行 `lines.append(...)` / `lines.extend(...)`，可读性一般。可以拆为一个多行 f-string 模板 + 动态部分拼接：

```python
header = textwrap.dedent(f"""\
    # AutoProxy Run Report

    - Session: {artifacts.session_tag}
    ...
""")
```

---

### 💡 `build_parser` 中 subcommand 注册逻辑可以更声明式

```python
# 当前：通过 if name == "xxx" 逐个添加参数
if name == "openbao-import":
    subparser.add_argument(...)
if name == "run":
    subparser.add_argument(...)
```

随着命令增多，这段会越来越长。可以改成：

```python
COMMANDS = {
    "openbao-get": (cmd_openbao_get, []),
    "openbao-import": (cmd_openbao_import, [
        {"flags": ["--file"], "required": True, "help": "Path to proxy JSON file."}
    ]),
    "run": (cmd_run, [
        {"flags": ["--session-tag"], "required": True}
    ]),
    ...
}
```

---

## 4. 测试覆盖盲区

| 场景 | 当前状态 |
|---|---|
| `_resolve_env` 递归展开 dict/list | ❌ 无测试 |
| `load_config` 遇到缺失 env var 时报错 | ❌ 无测试 |
| `TxtProxySource` 全为空行或注释时抛出 ValueError | ✅ `test_txt_source.py` 已有 |
| OpenBao `write_proxy` / `write_proxies_from_file` | ✅ `test_openbao_source.py` 已有 |
| AdsPower `find_proxy` 超过第一页 200 条 | ❌ 无测试（设计上未覆盖） |
| `_write_config_atomic` YAML 验证失败时临时文件清理 | ❌ 无测试（Bug 1 对应） |
| `merge_config` 传入空字符串（新文件场景） | ❌ 无测试（空 YAML 会 `yaml.safe_load` 返回 `None`，代码有 `or {}` 处理，但未经测试） |
| `test_clash_adapter_requires_base_proxy_a` 用 try/else 而非 `pytest.raises` | ⚠️ 可改用 `pytest.raises` 更 Pythonic |

---

## 5. 次要风格建议

- **`autoproxy/adapters/__init__.py`** 目前只有 52 字节（几乎空），建议把 Protocol 定义放进来作为公开接口。
- **`pyproject.toml`** 缺少 `[tool.ruff]` 或 `[tool.mypy]` 配置，项目目前无 lint/type-check CI 守护。
- **`configs/clash-verge-standard.yaml.bak`** 是由 `_write_config_atomic` 生成的备份文件，不应被 Git 跟踪，建议加入 `.gitignore`。
- **`config.local.example.json` 已删除**，当前保留 `config.openbao.example.json` 作为唯一示例配置入口。
- `ValidationResult.to_dict()` 手动拼字典但父类 `ProxyRecord.to_dict()` 用 `asdict(self)`——风格不统一。`ValidationResult` 也可以直接用 `asdict(self)`。

---

## 总结优先级

| 优先级 | 问题 |
|---|---|
| 🔴 立即修复 | 临时文件泄露（`_write_config_atomic`）|
| 🟡 近期改进 | session 用 `requests.Session()`；分页查重；`Sub2ApiAdapter.token` 状态管理 |
| ⚡ 中期重构 | 定义 Protocol；工厂注册表；`autoproxy.py` 拆分 |
| 💡 低优先级 | `base_url` 属性封装；Markdown 渲染精简；测试补全 |
