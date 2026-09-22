# P13 Dashboard — Playwright E2E 测试计划

> 状态：已按 review-20260923 修订 · 编写日期：2026-09-22 · 修订日期：2026-09-23
> 对应文件：`tests/e2e/test_console_dashboard.py`（28 测试 / 6 类）
> 目标：用真实浏览器（Chromium headless）完整走通 Enhanced Dashboard 用户旅程生命周期，覆盖事件流每一环。
> ⚠️ 执行前必加：`pytestmark = pytest.mark.e2e`（当前缺失，见 §2.5 脚注）。

---

## 一、背景与动机

P13 Enhanced Dashboard 在 Phase 3 结束后交付，声称"可运行"但用户实测报告三个致命 bug：

1. **calls 始终显示 0** —— generator WebSocket 推的是嵌套结构 `{attributes: {active_calls, ...}}`，console 直接读顶层 `d.active_calls` → 永远是 `undefined`
2. **Stop 按钮永远不可点** —— generator `_default_getter()` 没返回 `running: bool` 字段，console 读 `d.running || false` 永远走 false 分支
3. **点 Rules 菜单后找不到返回** —— `.vw` 视图 div 有两份拷贝（一份在 `.grid` 内、一份在 `.grid` 外），切换后 dashboard `.centre` 被隐藏但非 dashboard 视图不可见，用户卡死

这些 bug 不是单元测试能抓到的——它们横跨 generator（Python）→ FastAPI WS（Python）→ console 前端（JS）三层。E2E 测试必须用真实浏览器在真实进程栈上跑。

---

## 二、测试架构

### 2.1 进程栈（session scope，4 个独立进程）

| 进程 | 监听地址 | 启动命令 | 健康检查 |
|------|----------|----------|----------|
| Core Mock UAS | UDP :5061 | `.venv/bin/python -m s_sbc_mock.main --listen-port 5061 --trunk-port 15060` | ——（UDP，只收 INVITE） |
| Translation AS | SIP UDP :5060, API HTTP :8080 | `SBC_PEER_PORT=5061 RULES_FILE=<temp>` `.venv/bin/python -m as_app.main` | `GET /healthz` → `{"status":"ok", "version":"1.0.0"}` |
| Load Generator | HTTP :8765 | `.venv/bin/python tools/call_load_generator.py --as-port 5060 --http-port 8765` | `GET /load/status` → 非空 JSON |
| Enhanced Console | HTTP :8081 | `.venv/bin/python -m console.main --port 8081 --as-api-url http://127.0.0.1:8080 --load-api-url http://127.0.0.1:8765` | `GET /healthz` → `{"status":"ok"}` |

### 2.2 技术选型

| 项 | 选择 | 理由 |
|----|------|------|
| 测试框架 | 系统 Python `playwright 1.60.0` | venv 里没装 playwright，系统用户级已装 chromium-1243 |
| 测试风格 | pytest 风格（非 playwright 原生 config） | 与现有 pytest 测试体系统一 |
| 启动方式 | 自研 session fixture 起进程 | pytest-playwright 的 `webServer` 只支持单进程，我们是 4 个 |
| 浏览器 | Chromium headless | 系统已有，够用 |
| 额外依赖 | `requests` | `test_console_dashboard.py` §T3 用 `requests.put` 禁用 T4 call type。**当前未在 pyproject 显式声明**，依赖系统 python 的已有安装 |

> **已知缺口**（review-20260923 P0-2）：
> - `pyproject.toml` L81 开了 `--strict-markers`，`Makefile` L65 跑 `pytest tests/e2e -m e2e`，但本文件**未**声明 `pytestmark = pytest.mark.e2e`，导致 `make e2e` / `make test` **静默跳过**这 28 个测试。其余 3 个 E2E 文件（`test_call_flows.py`, `test_chained_call_flows.py`, `test_fraud_call_flows.py`）都有。
> - `conftest.py` L26 `PROJECT_ROOT = "/home/shudong/project/3rtparty_AS_POC"` 是硬编码绝对路径，换机器或 clone 到别处会炸。应改为 `pathlib.Path(__file__).resolve().parents[2]`。
> - playwright / requests 依赖未入 pyproject（只有"系统用户级已装"的前提），CI 不可复现。

### 2.3 Fixture 设计（`tests/e2e/conftest.py`）

```python
@pytest.fixture(scope="session")
def demo_stack():
    """启动 4 个进程，yield URLs，tearDown 时全杀。"""
    procs = []
    # 1. core mock（UDP :5061）
    # 2. translation AS（:5060 / :8080）
    # 3. load generator（:8765）
    # 4. enhanced console（:8081）
    
    # 轮询 healthz × 4，全部 OK 才往下走
    yield {
        "console": "http://127.0.0.1:8081",
        "as_api": "http://127.0.0.1:8080",
        "gen": "http://127.0.0.1:8765",
    }
    # tearDown: terminate() + wait(timeout=5)
```

关键点：
- **session scope** —— 整个测试会话只启一次进程栈（4 进程启动 ~15s）
- 端口固定（5061/5060/8080/8765/8081），conftest 启动前会 **`lsof -ti :PORT | kill -9`** 清扫占用端口的任何进程——**不区分进程归属**，在开发机上可能误杀其他服务
- RULES_FILE 在 conftest 里生成临时文件，把所有 next_hop ports 改成 5061（避免端口冲突）
- **完整 teardown 序列**：① 对每个 Popen 发 `SIGTERM` → ② `wait(timeout=5)` 等优雅退出 → 超时则 `kill()` → ③ 最后再 `_kill_port` 清扫 5 个端口确保无残留。conftest L177–189 实现，之前文档只写"terminate + wait"。

### 2.4 每个测试的 per-test reset

虽然 fixture 是 session scope，但 generator 状态会跨测试泄漏（前一个测试 Start 后没 Stop，后一个测试就从 running=true 开始）。因此每个测试体开头必须调：

```python
def _open_console(page, demo_stack):
    _reset_gen(demo_stack["gen"])   # POST /load/stop → 等 running=false & active_calls=0
    page.goto(demo_stack["console"])
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
```

generator 的 `active_calls` 有 bursty 特征：duration classes 里 **D1=2.5s (30%)、D2=11.5s (50%)、D3=25s (15%)、D4=3s timeout (5%)**。加权平均 9.5s 用于 Little's Law 耦合（`AVG_DURATION_SECONDS = 0.30×2.5 + 0.50×11.5 + 0.15×25 + 0.05×3 = 9.5`），不是运行时观测值。D1 的 2.5s 是 *midpoint*（`DurationModel.MIDPOINTS["D1"]=2.5`），其 WEIGHTS 注释写"~2 s conversation"是描述性口径，数值口径以代码为准。

call load 模型本身把 D1 设得很短是有意设计（模拟客服快速应答就 BYE），**加上 generator pool_feed 每秒快照一次，短 calls 在两次快照间完全 drain 是正常现象**——测试用 polling（deadline-based）而非 snapshot 断言。

### 2.5 执行命令

> ⚠️ **marker 缺口**（review P0-2）：当前 `test_console_dashboard.py` 没有 `pytestmark = pytest.mark.e2e`，而 `pyproject.toml` 开了 `--strict-markers`。**裸运行是唯一方式**——加 `-m e2e` 会静默跳过这 28 个。加上 marker 后再用 `-m e2e` / `make e2e`。

```bash
# 全部 28 测试（当前唯一可用方式 —— 不加 -m）
timeout 360 python3 -m pytest tests/e2e/test_console_dashboard.py -v

# 加上 pytestmark = pytest.mark.e2e 后，以下也能跑：
python3 -m pytest tests/e2e/ -m e2e -k "console_dashboard" -v
make e2e   # = pytest tests/e2e -m e2e（加 marker 后才覆盖本文件）

# 单层筛选
python3 -m pytest tests/e2e/test_console_dashboard.py -v -k "PageLoad"
python3 -m pytest tests/e2e/test_console_dashboard.py -v -k "Navigation"
python3 -m pytest tests/e2e/test_console_dashboard.py -v -k "GeneratorLifecycle"
python3 -m pytest tests/e2e/test_console_dashboard.py -v -k "DashboardLive"
python3 -m pytest tests/e2e/test_console_dashboard.py -v -k "AsRestEndpoints"
python3 -m pytest tests/e2e/test_console_dashboard.py -v -k "Concurrent"
```

预计耗时：**~130 秒**（4 进程启动 ~15s + 28 测试 × ~4s）。

---

## 三、测试用例清单（28 个 / 6 类）

### 3.1 TestPageLoad（5 个）—— 基础连通性，失败则中止后续

> ⚠️ 下表断言描述已按 review-20260923 P0-1 对齐到实际代码（不是最初 draft 声称的强度）。

| # | 测试名 | 核心断言（代码实际） | 与 draft 差异 |
|---|--------|---------------------|----------------|
| 1 | `test_page_loads_without_js_errors` | ① `page.on("pageerror")` 收集 → 最终 `len=0` ② `page.evaluate("typeof Chart") == "function"` | draft 声称有 title 断言，实际没有 |
| 2 | `test_all_nav_buttons_present` | ① `.nav button.count() >= 5`（代码写死 >=5，不是==6）② texts 里有 Dashboard + Rules + About（**只校验这三个**，不是 6 个）③ Dashboard 第一个按钮有 `act` class | draft 声称"6 个按钮全部可见且可点击"——可点击未校验；只验了 3 个文本 |
| 3 | `test_status_bar_renders` | 8 个 DOM id 各存在一个：`aDot, aSt, aInst, aVer, aUp, aCal, aAct, aTgt` | draft 写了"Load"字段——实际没有 Load id |
| 4 | `test_both_websockets_connect` | `#wsEv` + `#wsLd` 的 inner_text 含 "live"，轮询 ≤ 10s 成功 | 一致 |
| 5 | `test_initial_dashboard_controls_state` | ① `#btnStop.is_disabled()` 为 True ② `#gaugeVal.inner_text` 以 `"0 /"` 开头 | draft 声称验证 btnStart enabled——代码没验 btnStart（用 Stop disabled 反证 generator idle）|

### 3.2 TestNavigation（8 个）—— SPA 视图切换

| # | 测试名 | 核心断言（代码实际） | 备注 |
|---|--------|---------------------|------|
| 6 | `test_call_trace_view_renders` | ① 点 Call Trace → `#vw-call-trace.classList.contains('act')` True ② `.nav` count == 1（没丢）③ `.nav button[data-v="call-trace"].classList.contains('act')` | **不**断言其他视图不可见（只 #13 部分覆盖）。选择器是 `#vw-*` id + `classList.contains('act')`，不是 draft 写的 `.vw-*` class |
| 7 | `test_rules_view_renders_and_has_content` | ① `#vw-rules.classList.contains('act')` ② `#rulesCard.inner_text` 非空 | draft 声称"找到 ≥ 3 条规则卡片 `.rule-card`"——实际只验 inner_text 非空，无条数、无 `.rule-card` 选择器 |
| 8 | `test_screening_view_renders` | ① `#vw-screening.classList.contains('act')` ② `#scrCard.count() == 1` | 一致（draft 没提 #scrCard） |
| 9 | `test_statistics_view_renders` | ① `#vw-statistics.classList.contains('act')` ② `#statsCard.count() == 1` | 一致 |
| 10 | `test_about_view_renders` | ① `#vw-about.classList.contains('act')` ② inner_text 含 `"third-party"` | 一致 |
| 11 | `test_nav_stays_visible_after_each_view` | 遍历 5 个非 dashboard 视图 → 每步 `.nav.count() == 1` + 当前按钮有 `act` | 不验证其他按钮的 act 状态（只验证当前点击的那个）|
| 12 | `test_round_trip_rules_to_dashboard` | ① 点 Rules → `#vw-rules.act` ② 点 Dashboard → `#vw-dashboard.style.display != "none"` + `#vw-rules.classList.contains('act') == False` | draft 写的是"`.centre` 恢复可见"——代码用 `#vw-dashboard.style.display` 检查（两者等价，但实现更精确）|
| 13 | `test_all_views_then_back_to_dashboard` | 遍历 5 个视图 → 每个 `#vw-{view}.act` 在结束后为 False → `#vw-dashboard.style.display != "none"` | 这是唯一验证"其他视图不可见"的测试 |

### 3.3 TestGeneratorLifecycle（4 个）—— Start/Stop 生命周期

| # | 测试名 | 核心断言（代码实际） | 备注 |
|---|--------|---------------------|------|
| 14 | `test_start_button_hits_rest_endpoint` | **点 #btnStart → page.wait_for_timeout(500) → 直接 `_gen_status("/load/status")` 验证 `running=True`** | draft 声称"监听浏览器 response 事件 → 收到 POST /load/start"——**实际没有任何 response 监听**，是点了按钮后直接 REST 轮询 |
| 15 | `test_active_calls_rise_after_start` | Start → deadline 20s 轮询 REST `/load/status` → 看到 `active_calls > 0`（用 `ever_had` boolean，不假设峰值）| 一致 |
| 16 | `test_stop_button_drains_active_to_zero` | Stop → deadline 15s → 同时满足 `running=False` 且 `active_calls=0` | 一致 |
| 17 | `test_console_gauge_rises_then_falls_with_generator` | 4 阶段：① **先** `requests.put /load/config` 禁用 T4（用实际 `requests` 库，imported inline at L308）② generator REST active_calls > 0 至少一次 ③ console `#gaugeVal.inner_text` 非零至少一次 ④ Stop → 两个 drain 断言 | draft 没提 `requests` import；T4 disable 用 inline try/except；gauge 断言用 deadline polling 不是 snapshot |

### 3.4 TestDashboardLive（5 个）—— 实时图表

> 图表用 `_read_chart()` helper（L76-84），走 `Chart.getChart(el)` 读，不是 draft 里的 `el.__chart__`。

| # | 测试名 | 核心断言（代码实际） | 与 draft 差异 |
|---|--------|---------------------|----------------|
| 18 | `test_line_chart_accumulates_points` | Start → wait 6s → `Chart.getChart(lineChart).data.labels.length >= 4` | draft 写 `>= 6`，实际代码是 `>= 4` |
| 19 | `test_pie_chart_has_nonzero_segments` | Start → wait 8s → `sum(pieChart.data.datasets[0].data) >= 3` | 一致（代码结构是 `sum(segments) >= 3`）|
| 20 | `test_topology_svg_links_change_on_active` | ① 读 idle 态 `#l1.getAttribute('stroke-width')` ② Start → deadline 20s 轮询 → 找到 `active_sw > idle_sw + 0.1` ③ 否则 assert False + dump console 内部 state (activeCalls, counters, topoVal, l1_sw) | 文档 4.3 节描述"Math.max(activeCalls, counters.active, totalTraffic)"是准确的。draft §3 声称"> 1"——实际是浮点比较 `active_sw > idle_sw + 0.1`（idle 基线通常≈1.0，比较增量 0.1）|
| 21 | `test_trace_panel_accumulates_call_records` | Start → wait 8s → `#tlist .ti` count `>= 3` | draft 写 `>= 5`，实际代码是 `>= 3` |
| 22 | `test_trace_filter_narrows_list` | ① 取 `total_before = #tlist .ti count` ② **若 0 → `pytest.skip()`** ③ 输入 `"zzzzzzzNoMatchzzzzz"`（必然不匹配的字符串）④ assert `after_nomatch <= total_before` | **pytest.skip 在 L436 调用，但文件头部没 `import pytest`**——若 count==0 会抛 `NameError` 而非 skip（review P0-3 已发现）。另外输入的是必然不匹配字符串，断言的本质是"filter 没让列表变多"，不是真验证"筛选缩小了" |

### 3.5 TestAsRestEndpoints（4 个）—— AS 后端 REST API

| # | 测试名 | 核心断言 | 为什么重要 |
|---|--------|----------|------------|
| 23 | `test_healthz` | `GET /healthz` → 有 `status`, `version`, `uptime_seconds` | 基本健康检查 |
| 24 | `test_metrics` | `GET /api/v1/metrics` → 有 `counters`, `peer_status`, `calls_by_disposition` | metrics 数据结构 |
| 25 | `test_rules` | `GET /api/v1/rules` → 有 `rules` 列表，长度 ≥ 3，每条有 `rule_id`, `priority`, `action` | 规则列表加载 |
| 26 | `test_traces_list_has_calls_key` | `GET /api/v1/traces` → 返回 dict，有 `"calls"` 键（不是裸 list）| traces API 数据结构正确 |

### 3.6 TestConcurrentViewSwitchAndGenerator（2 个）—— 并发场景

| # | 测试名 | 核心断言 | 为什么重要 |
|---|--------|----------|------------|
| 27 | `test_generator_runs_survives_navigation` | Start generator → 遍历 5 个视图 → 回 Dashboard → generator 仍 running | View 切换不中断 WS |
| 28 | `test_stop_after_view_hops_resets` | 同上 + Stop → drain 到 0 | 并发 Stop 正常 |

---

## 四、关键技术细节

### 4.1 Playwright 等待策略

FastAPI 页面是同步返回的，但 JS WS 连接是异步的。**必须**显式等待：

```python
page.goto(f"{base_url}/")
page.wait_for_load_state("networkidle")
page.wait_for_timeout(2000)  # 额外等 2s 让 JS 初始化完成
```

**绝对不能**只靠 `wait_for_load_state("domcontentloaded")`——那时 inline `<script>` 还没跑。

### 4.2 字段路径对比（console vs generator）

| 来源 | 字段路径 | console 读 | 状态 |
|------|----------|------------|------|
| generator WS (`/ws/pool`) | `msg.attributes.active_calls` | `onPoolStatus(d) → s = d.attributes \|\| d → s.active_calls` | ✅ 已修复 |
| generator REST (`/load/status`) | 扁平 `active_calls`, `running` | 同上（fallback 自动处理） | ✅ **真实路径**（pool.snapshot）有 running；**库 fallback**（_default_getter）仍缺 running（§六 B2）|
| AS WS (`/ws/p12/events`) | `msg.event`, `msg.call_id` | 直接读 `d.event`, `d.call_id` | ✅ |

> **命名漂移**：`phase3-plan.md` 写 `/ws/events` 和 `/ws/load`，实际实现是 `/ws/p12/events` 和 `/ws/pool`（`src/console/main.py` L223-224）。本文档 2.1 / 2.3 / 4.2 都是实际端点名。

### 4.3 topology stroke-width 计算

`updateTopology()` 用三项取最大：
- `instantActive = Math.max(activeCalls, counters.active)` —— generator WS + AS event 两个源
- `totalTraffic = counters.completed + counters.rejected_608 + counters.timeout` —— 累计 traffic
- `intensity = Math.min(8, 1 + instantActive * 0.6 + Math.min(3, totalTraffic * 0.03))`

这样即使 D1=2.5s 的 calls 在 pool_feed 两次 1s 快照间完全 drain，totalTraffic 仍能让链路保持非 idle（测试用 float 比较避免整数截断误判）。

### 4.4 gauge bursty 处理

CallPool 的 D1 calls 是 2.5s 就 BYE，target_concurrency=10 时 active_calls 在 0-3 之间 oscillate（AS 会 reject 部分 calls + D1 太快 drain）。测试策略：
1. 先 PUT `/load/config` 禁用 T4 call type（"1234" 无路由 → AS 瞬时 reject → active_calls 永远低）
2. gauge 断言用 deadline-based polling，不假设"任何时刻 active_calls ≥ 5"
3. generator REST `/load/status` 作为权威源，console gauge 作为 WS 是否正常的验证

### 4.5 读 Chart.js 内部状态

Chart.js 4.x 用全局 `Chart.getChart(el)` 取实例（比 `el.__chart__` 更稳——后者是早期 Chart.js 4.x 还未正式暴露的 API，正式推荐就是 `Chart.getChart`）。测试的 `_read_chart()` helper（L76-84）这样写：

```python
labels = page.evaluate("""() => {
    var c = Chart.getChart(document.getElementById('lineChart'));
    if (!c) return null;
    return c.data.labels.length;
}""")
assert labels >= 4  # 实际阈值，不是 6（见 §3.4 #18）
```

### 4.6 读 generator REST 验证 WS 推送确实生效

```python
def _gen_status(gen_base: str) -> dict:
    with urllib.request.urlopen(f"{gen_base}/load/status") as r:
        return json.loads(r.read())

# 直接 urllib 不经过浏览器，验证 generator 进程真实状态
assert _gen_status(gen_base)["running"] is True
```

---

## 五、执行顺序

> §五是**建议的排查 gate 顺序**（快速 smoke → 逐层定位），**不是 pytest 实际执行顺序**。pytest 按文件内 `class` 定义顺序跑，实际是：PageLoad → Navigation → **GeneratorLifecycle** → DashboardLive → **AsRestEndpoints** → Concurrent。要按建议顺序执行必须加 `-k` 显式筛选。

```
【建议排查顺序】（与 pytest 实际顺序不同）
1. 跑 TestPageLoad（5 个）
   └─ 若任何失败 → 修 UI / JS 初始化 → 重跑 → 不进入后续
2. PageLoad 全绿 → 跑 TestNavigation（8 个）
   └─ 每个失败对应具体导航 bug
3. Navigation 全绿 → 跑 TestAsRestEndpoints（4 个）
   └─ 验证 AS API 端到端可达（REST 不依赖 console 渲染）
4. 跑 TestGeneratorLifecycle（4 个）
   └─ generator end-to-end（T3 → T4 → dashboard 链路）
5. 跑 TestDashboardLive（5 个）
   └─ 图表在 generator 运行时的数据验证
6. 跑 TestConcurrent（2 个）
   └─ 并发场景不回退
```

全部 **28 个绿** → 通过。

### 5.1 相对于 phase3-plan.md 的覆盖缺口（review P1-1）

`docs/phase3-plan.md` P13 Stage 4 对 E2E 有明确要求，本 28 测试**未覆盖**的项：

| phase3-plan 出处 | 要求 | 本 28 测试现状 |
|---|---|---|
| §P13 Stage 4 E2E step (5)(6) + §6 风险表第 4 行（High） | "slide to 5 → verify chart drops"——slider → REST `/load/config` → pool → WS → gauge chart **完整闭环** | 本文件无任何 slider E2E。#17 用 `requests.put /load/config` 禁用 T4 作为测试前置，但**不**断言 slider UI → REST → pool 响应链路。phase3-plan 将其列为影响 High 风险 |
| REQ-F-049 | call type toggles E2E | 无 |
| REQ-F-048 / §P13 Stage 3 step 7 | 拓扑按 hop 颜色（绿/红/橙） | 本文件只测 `#l1 stroke-width`，颜色（stroke CSS var）未测 |
| §P13 "chained demo compatibility" / D8 | 拓扑为 SBC → anti-fraud → translation → core 四节点链式 | conftest 只起 1 个 AS（translation），无 anti-fraud 进程。拓扑最左两跳在 E2E 栈里不存在。**chained 拓扑覆盖在 `test_chained_call_flows.py`（非浏览器 E2E）和 `test_chained_topology.py`（integration），console dashboard 的拓扑图渲染链式场景未测** |

→ **建议**：至少补一个"slider 改 target_concurrency → gauge/target 读数随 pool_status_update 变化"闭环测试。其余缺口在 `docs/testing/e2e-call-flows-plan.md` 和 `docs/testing/integration-plan.md` 有覆盖，不再此处重列。

---

## 六、Bug 历史（已修复）

| # | Bug | 根因 | 修复 |
|---|-----|------|------|
| B1 | calls 始终显示 0 | console 读 `d.active_calls` 但 generator WS 推 `d.attributes.active_calls` | `onPoolStatus(d) → s = d.attributes \|\| d` |
| B2 | Stop 按钮永远不可点 | generator 正常运行时，console 读 generator REST 返回值里的 `running` 字段；**正常路径**（`build_generator_app(pool_state_getter=pool.snapshot)`，`snapshot()` L248 有 `"running": self.is_running`）下字段存在；**但库模式 fallback**（`_default_getter()` L729-737）至今**没有** `running` 字段——B2 的"修复"路径不是补 `_default_getter()`，而是真实 generator 进程总用 `pool.snapshot`。测试代码 `_reset_gen` 里 `.get("running", True)` 默认值掩盖了这个缺口（若 generator 进程死了 REST 返回 default，会被误认为 running）| **未完全修**：真实进程 OK，库 fallback 仍缺 `running`。本测试文件每次 reset 都用 REST 验证 running=false 后才开始测试，规避了这个坑 |
| B3 | Rules 菜单后找不到返回 | `.vw` 视图 div 有两份拷贝（一份在 `.grid` 内、一份在外），切 dashboard `.centre` 被隐藏后非 dashboard 视图不可见 | 移进 grid + 加 `grid-column:2;grid-row:1` |
| B4 | topology stroke-width 永远 1 | 读 generator WS 的 activeCalls 但 D1 BYE 太快 drain → 快照总是 0 | `Math.max(activeCalls, counters.active, totalTraffic)` |
| B5 | gauge 永远显示 `0 / 10` | T4 call type 被 AS reject 后 active_calls 永远低，D1 BYE 太快 pool_feed 快照总是 0 | gauge 测试先 `PUT /load/config` 禁用 T4 |
| B6 | CallPool.stop() 不 drain active calls | `_on_call_ended()` 在 ED2 线程调 `asyncio.get_event_loop()` → RuntimeError → active_calls 不减 | 强制 `asyncio.run_coroutine_threadsafe()` + `force_disconnect_all()` |

> **B2 的后续建议**（review P1-3）：顺手给 `_default_getter()` 也加上 `"running": False`（本来就是 idle 默认态），消除库模式 fallback 与生产路径的差异。否则下次有人用库模式写测试会再踩同样的坑。
