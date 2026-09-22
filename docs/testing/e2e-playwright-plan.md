# P13 Dashboard — Playwright E2E 测试计划

> 状态：已实现 · 编写日期：2026-09-22 · 更新日期：2026-09-23
> 对应文件：`tests/e2e/test_console_dashboard.py`（28 测试 / 6 类）
> 目标：用真实浏览器（Chromium headless）完整走通 Enhanced Dashboard 用户旅程生命周期，覆盖事件流每一环。

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
- 端口固定（5061/5060/8080/8765/8081），conftest 启动前会 kill 占用端口的旧进程
- RULES_FILE 在 conftest 里生成临时文件，把所有 next_hop ports 改成 5061（避免端口冲突）
- teardown 必须干净，否则第二次跑会端口冲突

### 2.4 每个测试的 per-test reset

虽然 fixture 是 session scope，但 generator 状态会跨测试泄漏（前一个测试 Start 后没 Stop，后一个测试就从 running=true 开始）。因此每个测试体开头必须调：

```python
def _open_console(page, demo_stack):
    _reset_gen(demo_stack["gen"])   # POST /load/stop → 等 running=false & active_calls=0
    page.goto(demo_stack["console"])
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
```

generator 的 `active_calls` 有 bursty 特征：duration classes 里 D1=2.5s (30%)、D2=11.5s (50%)、D3=25s (15%)、D4=3s timeout (5%)，加上 generator pool_feed 每秒快照，**短 calls 在两次快照间完全 drain 是正常现象**——测试用 polling（deadline-based）而非 snapshot 断言。

### 2.5 执行命令

```bash
# 全部 28 测试
timeout 360 python3 -m pytest tests/e2e/test_console_dashboard.py -v

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

| # | 测试名 | 核心断言 | 为什么重要 |
|---|--------|----------|------------|
| 1 | `test_page_loads_without_js_errors` | ① `pageerror` 事件为 0 条 ② `typeof Chart === 'function'` ③ title 包含 "Console" | JS bundle 完整性，Chart.js 不报错 |
| 2 | `test_all_nav_buttons_present` | 6 个导航按钮（Dashboard / Call Trace / Rules / Screening / Statistics / About）全部可见且可点击 | 导航 UI 结构正确 |
| 3 | `test_status_bar_renders` | 状态栏 8 个字段（Status / Instance / Uptime / Version / Calls / Active / Target / Load）全部渲染 | 健康检查初始状态 |
| 4 | `test_both_websockets_connect` | ① `#wsEv.className` 包含 `live` ② `#wsLd.className` 包含 `live` | 两条 WS（AS events + generator pool）都连上 |
| 5 | `test_initial_dashboard_controls_state` | ① btnStart enabled ② btnStop disabled ③ gaugeVal 显示 `0 / 10` | 页面初始态正确 |

### 3.2 TestNavigation（8 个）—— SPA 视图切换

| # | 测试名 | 核心断言 | 为什么重要 |
|---|--------|----------|------------|
| 6 | `test_call_trace_view_renders` | 点 Call Trace → `.vw-call-trace.act` 可见，`.vw-rules` 不可见 | 视图切换生效 |
| 7 | `test_rules_view_renders_and_has_content` | 点 Rules → 找到 ≥ 3 条规则卡片（`#rulesList .rule-card`） | Rules 数据加载成功 |
| 8 | `test_screening_view_renders` | 点 Screening → `.vw-screening.act` 可见 | 视图渲染 |
| 9 | `test_statistics_view_renders` | 点 Statistics → `.vw-statistics.act` 可见 | 视图渲染 |
| 10 | `test_about_view_renders` | 点 About → `.vw-about.act` 可见，文本包含 "third-party" | About 页面渲染 |
| 11 | `test_nav_stays_visible_after_each_view` | 遍历 5 个非 dashboard 视图 → `nav.col` 始终可见 | 导航不丢（修复后） |
| 12 | `test_round_trip_rules_to_dashboard` | 点 Rules → 再点 Dashboard → `.centre` 恢复可见 | 往返正常 |
| 13 | `test_all_views_then_back_to_dashboard` | 遍历 5 个视图 → 每个只允许一个 `.act` → 最后回 Dashboard | 互斥切换 + centre 恢复 |

### 3.3 TestGeneratorLifecycle（4 个）—— Start/Stop 生命周期

| # | 测试名 | 核心断言 | 为什么重要 |
|---|--------|----------|------------|
| 14 | `test_start_button_hits_rest_endpoint` | 监听浏览器 `response` 事件 → 点 Start → 收到 `POST /load/start` | 按钮 click handler 路径正确 |
| 15 | `test_active_calls_rise_after_start` | Start → 轮询 generator REST `/load/status` → 看到 `running=true` 且 `active_calls>0` | 真实 calls 在产生 |
| 16 | `test_stop_button_drains_active_to_zero` | Stop → 等 → `running=false` 且 `active_calls=0`（包括 force_disconnect_all） | generator 正确 drain |
| 17 | `test_console_gauge_rises_then_falls_with_generator` | 4 阶段：① generator REST active_calls 上升 ② console gauge 显示非零 ③ Stop 后 active_calls=0 ④ gauge 恢复 `0 / 10` | 完整 end-to-end 生命周期（含 T4 call type disable 避免 AS 瞬时 reject） |

### 3.4 TestDashboardLive（5 个）—— 实时图表

| # | 测试名 | 核心断言 | 为什么重要 |
|---|--------|----------|------------|
| 18 | `test_line_chart_accumulates_points` | Start → 等 6s → line chart `data.labels.length ≥ 6`（每 500ms 推一次）| 折线图在增长 |
| 19 | `test_pie_chart_has_nonzero_segments` | Start → 等 → `chart.data[0]` 各段之和 ≥ 3 | 饼图计数器在增长 |
| 20 | `test_topology_svg_links_change_on_active` | Start → 等 20s → `#l1 stroke-width > 1`（Math.max(activeCalls, counters.active, totalTraffic) 后至少有 totalTraffic 贡献） | 拓扑图链路强度变化 |
| 21 | `test_trace_panel_accumulates_call_records` | Start → 等 → `#tlist .ti` 子元素 ≥ 5 | Trace 面板在增长 |
| 22 | `test_trace_filter_narrows_list` | 在 filter 框输入 call_id 片段 → 匹配列表长度减小 | 筛选功能 |

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
| generator REST (`/load/status`) | 扁平 `active_calls` | 同上（fallback 自动处理）| ✅ |
| AS WS (`/ws/p12/events`) | `msg.event`, `msg.call_id` | 直接读 `d.event`, `d.call_id` | ✅ |

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

Chart.js 4.x 在浏览器里注册为全局 `Chart`，实例挂在 DOM 元素的 `__chart__` 属性上：

```python
labels = page.evaluate("""() => {
    var c = document.getElementById('lineChart').__chart__;
    return c.data.labels.length;
}""")
assert labels >= 6
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

```
1. 跑 TestPageLoad（5 个）
   └─ 若任何失败 → 修 UI / JS 初始化 → 重跑 → 不进入后续
2. PageLoad 全绿 → 跑 TestNavigation（8 个）
   └─ 每个失败对应具体导航 bug
3. Navigation 全绿 → 跑 TestAsRestEndpoints（4 个）
   └─ 验证 AS API 端到端可达
4. 跑 TestGeneratorLifecycle（4 个）
   └─ generator end-to-end
5. 跑 TestDashboardLive（5 个）
   └─ 图表在 generator 运行时的数据验证
6. 跑 TestConcurrent（2 个）
   └─ 并发场景不回退
```

全部 **28 个绿** → 通过。

---

## 六、Bug 历史（已修复）

| # | Bug | 根因 | 修复 commit |
|---|-----|------|-------------|
| B1 | calls 始终显示 0 | console 读 `d.active_calls` 但 generator WS 推 `d.attributes.active_calls` | `onPoolStatus(d) → s = d.attributes \|\| d` |
| B2 | Stop 按钮永远不可点 | generator `_default_getter()` 无 `running` 字段 | 补上 `"running": ...` |
| B3 | Rules 菜单后找不到返回 | `.vw` 视图 div 有两份拷贝（一份在 `.grid` 内、一份在外），切 dashboard `.centre` 被隐藏后非 dashboard 视图不可见 | 移进 grid + 加 `grid-column:2;grid-row:1` |
| B4 | topology stroke-width 永远 1 | 读 generator WS 的 activeCalls 但 D1 BYE 太快 drain → 快照总是 0 | `Math.max(activeCalls, counters.active, totalTraffic)` |
| B5 | gauge 永远显示 `0 / 10` | T4 call type 被 AS reject 后 active_calls 永远 ≤ 3，D1 BYE 太快 pool_feed 快照总是 0 | gauge 测试先 PUT `/load/config` 禁用 T4 |
| B6 | CallPool.stop() 不 drain active calls | `_on_call_ended()` 在 ED2 线程调 `asyncio.get_event_loop()` → RuntimeError → active_calls 不减 | 强制 `asyncio.run_coroutine_threadsafe()` + `force_disconnect_all()` |
