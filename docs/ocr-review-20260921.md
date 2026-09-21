# OCR Review — main → phase2

- **工具**: Open Code Review (ocr)
- **范围**: `ocr review --from main --to phase2`
- **模型**: deepseek-v4.1-flash (Coding Plan)
- **日期**: 2026-09-21
- **规模**: 38 files reviewed, 15 comments

---

## P0 — 必须修复

### R-01. `call_controller` 重构后删除了空 next_hops 守卫，可能 IndexError

- **文件**: `src/as_app/call_controller.py:194`
- **严重度**: 运行时异常
- **问题**: 重构删除了原先在发起外呼前的显式守卫（`if not hops: raise AsError(ROUTE_NO_NEXT_HOP)` → 480 reject），现在直接对 `decision.next_hops[0]` 取下标，`next_hops=list(decision.next_hops)` 也假定列表非空。若路由引擎在 `Disposition.ROUTE` 下仍可能返回空的 `next_hops`，这里会抛 `IndexError`，调用方看到的是 500 而不是干净的 480。
- **建议**: 确认 `as_app.routing.engine.decide` 是否保证 ROUTE 决策必带至少一个下一跳。若不保证，补回守卫：

```python
if not decision.next_hops:
    return self._reject_decision(
        AsError(AsErrorCode.ROUTE_NO_NEXT_HOP, f"rule {decision.rule_id or '-'} selected no next hop", call_id=self.call_id),
        disposition=CallDisposition.REJECTED,
        rule_id=decision.rule_id,
    )
```

---

### R-02. Docker 镜像构建会因 `as-platform` 的 path 依赖直接失败

- **文件**: `deploy/docker-compose.yml:87-90`
- **严重度**: 构建阻塞
- **问题**: `anti-fraud-as` 服务沿用 `context: ..` + `deploy/Dockerfile.as`，但三个 Dockerfile 都只 `COPY pyproject.toml uv.lock ./` 然后 `uv sync --frozen`。本次 pyproject.toml 新增 `as-platform = { path = "../as_platform", editable = true }`，Docker build context 内根本没有 `../as_platform`，uv 在镜像构建时会直接失败。`make docker-up` 预期"五个服务 Up"实际无法成立。
- **建议**: 把平台库纳入构建上下文（compose 的 context 改为 `../..` 并调整 dockerfile 路径，或构建前把库同步进仓库内某目录再 `COPY`），或改为消费已发布的 wheel/git 源。

---

### R-03. `capacity_probe` 的 `completed` 统计漏掉 `released` 条件

- **文件**: `tools/capacity_probe.py:440`
- **严重度**: 数据错误
- **问题**: `LevelObservation.completed` 只判断了 `status == 200`，漏掉了 `released`。后果：
  1. 一个已收 200 OK 但仍在通话中的呼叫会同时计入 `completed` 和 `pending`，`completed + non_200 + pending > offered`，表格自相矛盾
  2. 降级判定 `if observation.completed < observation.offered` 会漏判（所有呼叫答了 200 但未在 cap 内释放不会被识别为降级）
- **建议**:

```python
completed = sum(1 for outcome in outcomes if outcome is not None and outcome.released and outcome.status == 200)
```

---

### R-04. `anti_fraud_probe` 的事件循环无超时，线程异常时主线程永久阻塞

- **文件**: `tools/anti_fraud_probe.py:238-239`
- **严重度**: 死锁
- **问题**: `ED2.loop()` 未设置超时，探测是否结束完全依赖 `send_invite` 线程执行到末尾的 `ED2.breakLoop()`。若该线程在 `bind`/`sendto`/`recvfrom` 处抛未捕获异常，`breakLoop()` 永不执行，主线程永久阻塞。
- **建议**: 在 `send_invite` 内用 `try/finally` 保证 `ED2.breakLoop()` 一定被调用，或给 `ED2.loop()` 加一个与 5 秒读取窗口相称的截止定时器。

---

### R-05. `as-platform` 用 `path` 源无版本锁定，`uv sync --frozen` 对它失效

- **文件**: `pyproject.toml:62`
- **严重度**: 不可复现构建
- **问题**: `path` 源没有可解析的版本，`uv sync --frozen` 会静默接受版本偏差，锁文件对平台库失去校验意义。本地与 CI 可能跑在不一致（甚至已损坏）的库上，行为漂移且难以定位。
- **建议**: 改为 `git` 源并固定 rev/tag：

```toml
as-platform = { git = "https://github.com/<owner>/as_platform.git", rev = "<pinned-commit>" }
```

---

## P1 — 应该修复

### R-06. CI clone `as_platform` 未固定 ref，上游破坏性提交会让门禁静默变红

- **文件**: `.github/workflows/ci.yml:50-51`
- **严重度**: CI 脆弱性
- **问题**: `--depth 1` 默认拉取默认分支 HEAD，同一份本仓库代码在不同时间会拉到不同的平台库版本。另外 clone 是 `uv sync` 的硬前置，按文件顶部 HONESTY 注释该库尚未发布，五个 job 会在安装依赖前全部失败。
- **建议**: 固定 ref（可用仓库变量承载），并让不可用时给出明确失败信息或与库的发布同批合入。

```yaml
- name: Clone the platform library beside this repository
  env:
    AS_PLATFORM_REF: ${{ vars.AS_PLATFORM_REF }}
  run: |
    git clone --depth 1 --branch "$AS_PLATFORM_REF" \
      https://github.com/${{ github.repository_owner }}/as_platform.git ../as_platform
```

---

### R-07. `as-platform` 未带版本约束，建议补 `>=0.1.0`

- **文件**: `pyproject.toml:28`
- **严重度**: 最低限度护栏
- **问题**: 即使保留 `path` 源，也建议补上最小版本约束，这样平台库版本落后于声明时 uv 会直接报错而不是静默使用。
- **建议**:

```toml
"as-platform>=0.1.0",
```

---

### R-08. `observability/tracing.py` 删除了 `DEFAULT_MAX_TRACED_CALLS` re-export，疑似疏忽

- **文件**: `src/as_app/observability/tracing.py:24-31`
- **严重度**: API 兼容性
- **问题**: tracing facade 不再转发 `DEFAULT_MAX_TRACED_CALLS`，但 sibling `logging` facade 保留了模块级常量（`LOG_FIELDS`、`DEFAULT_DIRECTION` 等），说明这是有意的设计模式。当前仓库内无引用所以不崩，但任何 `from as_app.observability.tracing import DEFAULT_MAX_TRACED_CALLS` 的外部消费者会 `ImportError`。
- **建议**: 重新 export 并加入 `__all__`，或确认已 intentionally dropped。

---

### R-09. `path_dependency_probe.py` 的 `next()` 无默认值，site-packages 找不到时抛裸 `StopIteration`

- **文件**: `tools/path_dependency_probe.py:264`
- **严重度**: 可用性
- **问题**: 一旦消费方虚拟环境不是 `lib/python*/site-packages` 布局（如 Windows `Lib/site-packages`，或 `uv sync` 失败留下半成品），抛裸 `StopIteration`，堆栈信息与真正原因无关，且中断整个报告。
- **建议**:

```python
found = next((consumer / ".venv" / "lib").glob("python*/site-packages"), None)
if found is None:
    raise RuntimeError(f"no site-packages directory under {consumer / '.venv' / 'lib'}")
return found
```

---

### R-10. `demo_chained_call.py` 与 `chained_as_probe.py` 约 120 行重复代码

- **文件**: `tools/demo_chained_call.py:105` / `tools/chained_as_probe.py`
- **严重度**: 可维护性
- **问题**: `draw_loop_until`、`verdict_attributes`、`decision_rule`、`_icid_of`、`_header_value`、`received_invite_icid` 以及建链/端口分配逻辑几乎逐字重复。两边将来只会各自漂移（本次新增 `--rules-file`/`--screening-file` 就改了两遍）。
- **建议**: 公共辅助抽到 `tools/` 下的共享模块，类似 `capture_call` 已在做的那样。

---

### R-11. Console 前端 404 时不 reject，anti-fraud 实例上 rules 分支成了死代码

- **文件**: `src/console/main.py:181,194`
- **严重度**: 功能不可用
- **问题**:
  1. `fetch` 在 404/503 时不 reject，`r.json()` 把 FastAPI 错误体赋给变量
  2. `/api/v1/rules` 只在 number-translation 实例上存在，anti-fraud 实例上恒返回 404
  3. `rd` 只要被赋过值就为真，本次新增的 `else if(sd)` screening 分支在 anti-fraud 实例上永远走不到
- **建议**: fetch 前校验 `r.ok`，两个 API 都检查。

---

## P2 — 低优先级

### R-12. CI workflow 未声明 `permissions`

- **文件**: `.github/workflows/ci.yml`
- **严重度**: 安全加固
- **问题**: 未声明 `permissions`，job 继承默认较宽权限；新增的跨仓库克隆还会使用 `actions/checkout` 持久化的凭据。
- **建议**:

```yaml
permissions:
  contents: read
```

---

### R-13. `chained_as_probe.py` docstring 数字与内容不符

- **文件**: `tools/chained_as_probe.py:22`
- **严重度**: 文档误导
- **问题**: docstring 写 "Three properties are observed here"，实际枚举了 4 条。
- **建议**: 改为 "Four properties"。

---

### R-14. `anti_fraud_as.call_controller._verdict` 是死状态

- **文件**: `src/anti_fraud_as/call_controller.py:202`
- **严重度**: 代码异味
- **问题**: `self._verdict` 只被赋值（此处与 `decide` 中），在本包内从未被读取。`decide` 之后用的是局部变量 `decision`，基类也不依赖它。
- **建议**: 删除该属性及其在 `decide` 中的赋值。若确需保留请注释说明消费者。

---

### R-15. `pyproject.toml` 用 `uv sync --frozen` 会静默接受 `as-platform` 版本偏差（R-05 详情）

- **状态**: 已归入 R-05
