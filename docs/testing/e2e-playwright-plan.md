# P13 Dashboard — Playwright E2E 测试计划

> 状态：已按 review-20260923 两轮修订（含 review-kimi 第二轮） · 编写日期：2026-09-22 · 最后修订：2026-09-23
> 对应文件：`tests/e2e/test_console_dashboard.py`（28 测试 / 6 类）
> 目标：用真实浏览器（Chromium headless）完整走通 Enhanced Dashboard 用户旅程生命周期，覆盖事件流每一环。

### 代码修复状态（review 两轮 + HY4 第三轮行动项）

| 项 | 位置 | 内容 | 状态 | 验收口径 |
|---|---|---|---|---|
| **P0-3** | `test_console_dashboard.py` L1 | 文件头加 `import pytest`（L436 `pytest.skip` 之前会 NameError） | ✅ **已修复** 2026-09-23 | generator 启动慢时 #22 正确 skip 而非假失败 |
| **P0-2a** | `test_console_dashboard.py` L21 | 加 `pytestmark = pytest.mark.e2e` | ✅ **已修复** 2026-09-23 | `pytest tests/e2e -m e2e` 收集 28 dashboard + 9 call flows = 37 |
| **P0-2b** | `conftest.py` L26 | PROJECT_ROOT 改 `pathlib.Path(__file__).resolve().parents[2]` | ✅ **已修复** 2026-09-23 | 换机器 clone 到别处不炸 |
| **P0-2c** | `pyproject.toml` dev 组 | 加 `pytest-playwright`（提供 `page` fixture）+ `playwright`（driver） | **待补** | 裸环境下 `uv run pytest ...` 可跑；**不是只加 `playwright`**（HY4 B-2） |
| **P0-2d** | `pyproject.toml` dev 组 | ⚠️ `requests` 已被移除（M-4 改 stdlib urllib），**不再需要声明** | ✅ 已解决 | — |
| **M-4** | `test_console_dashboard.py` L335-424 | 去 `requests`、改 `_put_config`、#17 try/finally 恢复原配置 | ✅ **已修复** 2026-09-23 | `pytest -k test_console_gauge_rises_then_falls_with_generator` 与全量顺序跑结果一致 |
| **M-5** | `test_console_dashboard.py` L46-79 | `_reset_gen` 区分不可达（立刻 fail）与超时（带诊断 fail） | ✅ **已修复** 2026-09-23 | 手动 kill generator 进程 → pytest.fail 给出清晰错误信息 |
| **R2-P2-3** | `conftest.py` L79 | 删 conftest 死副本 `_reset_gen` | ✅ **已修复** 2026-09-23 | conftest 无同名死代码；dashboard 文件那份是唯一版本 |
| **R2-P2-4 / N-2 / N-3** | `conftest.py` L113-154 | 4 进程日志落 per-session tmpdir、句柄 teardown 时关 | ✅ **已修复** 2026-09-23 | pytest session 结束后无 `/tmp/e2e-*` 残留；无 `PosixPath.close` teardown 错 |
| **R3-P0-1** | `test_console_dashboard.py` TestBindingConstraint | binding-constraint 配方方向纠正：`call_rate` 越大越 `"concurrency"`；PUT 响应不含该字段需再 GET | ✅ **已补测试** commit `68d189a`（36 测试 → 8 新增） | 新 REST 级 E2E：`{10, 0.1} → "rate"`；`{10, 2.0} → "concurrency"` |
| **R3-P1-2a** | `test_console_dashboard.py` TestDomUniqueness | DOM 唯一性 `#vw-{view}.count() == 1` | ✅ **已补测试** commit `68d189a` | 5 视图 parametrize；人为插第二份 `.vw-rules` → 测试红 |
| **R3-P1-2b** | `test_console_dashboard.py` TestWsOfflineReconnect | WS 离线重连（`set_offline True → False`） | ✅ **已补测试** commit `68d189a` | `#wsEv/#wsLd: live → offline → recover → live` |
| **R3-P1-4** | generator L105 + ADR-0013 L79 + HLD §12.4 + unit-plan + 2 处单测注释 | **9.5 vs 10.4 escalate to maintainer**——这是 ADR-0013 + HLD 共同确认的设计常量，不是某处注释写错；同步五处并改 `test_duration_model_avg_duration_constant` 为断言字面量 | **待裁决** | 五处数值一致；单测改为 `assert AVG_DURATION_SECONDS == 10.4` |
| **R3-P0-3 / B-3** | `Makefile` L65 + `pyproject.toml` + `.github/workflows/ci.yml` | **CI 接入方式待 maintainer 拍板**：正式接入（dev 组加 deps + `playwright install chromium`）vs 显式豁免（拆 `make e2e-ui` 进 gap register） | **待决策** | `ci.yml` 行为与本文档一致 |
| **R3-P2-3 / M-8** | `docs/production-gaps.md` | 登记端口硬编码 / `kill -9` / 浏览器依赖三条 | **待登记** | register 三行可追溯到本计划 |
| **R3-P2-4 / M-9** | `docs/acceptance/report.md` + `ci.yml` artifacts | E2E 证据路径 + 失败产出 `artifacts/` | **待落地** | `ci.yml` e2e-trace artifact 能拿到有效内容 |

→ 原第一轮追踪表的 6 项：P0-2/P0-3/R2-P0-1/R2-P1-1/R2-P2-3/R2-P2-4 已在此表重写，见上。

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
| 测试框架 | `pytest-playwright 0.8.0`（提供 `page` fixture）+ `playwright 1.60.0`（Chromium driver） | **不是只装 `playwright`**（HY4 B-2 发现）。`playwright` 是 driver/CLI，**`page` fixture 由 `pytest-playwright` 提供**。系统 Python 之所以能跑是同时装了两者 |
| 测试风格 | pytest 风格（非 playwright 原生 config） | 与现有 pytest 测试体系统一 |
| 启动方式 | 自研 session fixture 起进程 | pytest-playwright 的 `webServer` 只支持单进程，我们是 4 个 |
| 浏览器 | Chromium headless | 系统已有，够用；CI 需 `playwright install --with-deps chromium` |
| HTTP 客户端 | **stdlib `urllib.request`**（无额外依赖） | HY4 M-4 移除了 `requests` 库——`_gen_status`/`_as_get`/新 `_put_config` 全走 urllib，依赖面收窄，P0-2c 只需加 playwright + pytest-playwright |

> **已知缺口**（HY4 B-2 + B-3）：
> - `pyproject.toml` dev 组未声明 `pytest-playwright` + `playwright`（这是 **两个包**，不是一个），裸环境下 `uv run pytest tests/e2e/test_console_dashboard.py` 会报 `fixture 'page' not found`
> - **CI 接入方式待 maintainer 决策**：`ci.yml` e2e job 目前跑 `uv run pytest tests/e2e -m e2e`，加 marker 后这条 job 会立即报 fixture 缺失（B-3 blocker）。方案：(a) dev 组加 deps + `playwright install chromium` 并入 CI；(b) 拆出 `make e2e-ui` 并在 `docs/production-gaps.md` 登记为 POC 简化
> - `conftest.py` **之前** L26 的硬编码绝对路径已在 2026-09-23 修复为 `pathlib.Path(__file__).resolve().parents[2]` ✅

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

**代码卫生债务**（R2-P2-3 / R2-P2-4）：
- conftest L79-94 有一份 `_reset_gen`（8s deadline，仅查 `running`），本测试文件 L22-38 也有同名副本（10s deadline，查 `running` + `active_calls==0`）。本文件用的是自己的副本，conftest 版本疑似死代码。建议清理（见头部追踪表）。
- conftest L134 `open("/tmp/e2e-as.log", "w")` 句柄不关闭，并发会话互相覆盖。应改用 `tempfile.NamedTemporaryFile` + context manager。

### 2.4 每个测试的 per-test reset

虽然 fixture 是 session scope，但 generator 状态会跨测试泄漏（前一个测试 Start 后没 Stop，后一个测试就从 running=true 开始）。因此每个测试体开头必须调：

```python
def _open_console(page, demo_stack):
    _reset_gen(demo_stack["gen"])   # POST /load/stop → 等 running=false & active_calls=0
    page.goto(demo_stack["console"])
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
```

generator 的 `active_calls` 有 bursty 特征：duration classes 里 **D1=2.5s (30%)、D2=11.5s (50%)、D3=25s (15%)、D4=3s timeout (5%)**。加权平均 **10.4s** 用于 Little's Law 耦合（`AVG_DURATION_SECONDS = 0.30×2.5 + 0.50×11.5 + 0.15×25 + 0.05×3 = 0.75 + 5.75 + 3.75 + 0.15 = 10.4`）。注意：`tools/call_load_generator.py` L105 的行尾注释 `# = 9.5` 有误，代码实际算出来就是 10.4（Python 无浮点误差，0.30×2.5 精确 0.75）。该常量经 `compute_binding_constraint()`（L240）进入 Little's Law 的 binding-constraint 判定（ADR-0013），是设计口径常量而非装饰性数字。D1 的 2.5s 是 *midpoint*（`DurationModel.MIDPOINTS["D1"]=2.5`），其 WEIGHTS 注释写"~2 s conversation"是描述性口径，数值口径以代码为准。

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

预计耗时：**常规 ~200 秒 / 最坏 ~450 秒**（HY4 M-6 重新逐条累加得出）。分解：

| 类 | 轮询预算 | 常规（估） | 最坏（估） |
|---|---|---|---|
| T1 PageLoad (5) | 3s | ~18s | ~56s |
| T2 Navigation (8) | ~7s | ~45s | ~120s |
| T3 GeneratorLifecycle (4) | 20+20+15+10s | ~45s | ~110s |
| T4 DashboardLive (5) | 6+8+20+8+8=50s | ~50s | ~116s |
| T5 AsRestEndpoints (4) | 0 | ~1s | ~2s |
| T6 Concurrent (2) | ~10s | ~25s | ~30s |
| 4 进程启动 | — | ~15s | ~20s |

**建议命令**：`timeout 900`（原 `timeout 360` 在最坏情况会裁绿线）。**可削减块**：T4 五个测试的 `wait_for_timeout(6000/8000)` 合计 30s，是全套件最大固定等待块。

---

## 三、测试用例清单（28 个 / 6 类）

### 3.1 TestPageLoad（5 个）—— 基础连通性，失败则中止后续

> ⚠️ 下表断言描述已按 review-20260923 P0-1 对齐到实际代码（不是最初 draft 声称的强度）。
> REQ/ACC 映射按 HY4 §6 重写，依据 `docs/requirements/functional-and-nonfunctional.md`（L26、L56-64）
> 与 `docs/acceptance/criteria.md`（L131-139）。标"—"表示仓库无直接对应条目。
> **重要**：criteria.md 的 ACC-P13-001…006 当前验证命令全是 integration 层 `test_console.py`——本
> Playwright E2E 是**附加证据**（更靠近真实浏览器 + 完整 4 进程栈），不替换 integration 断言。

| # | 测试名 | 核心断言（代码实际） | 与 draft 差异 | REQ / ACC（HY4 修正） |
|---|--------|---------------------|----------------|----------------------|
| 1 | `test_page_loads_without_js_errors` | ① `page.on("pageerror")` 收集 → 最终 `len=0` ② `page.evaluate("typeof Chart") == "function"` | draft 声称有 title 断言，实际没有 | **REQ-F-050 / ACC-P13-006**（vendored Chart.js UMD bundle 能从 `/static/` 加载并跑起来——HY4 指出前版错标 REQ-F-045 折线图）|
| 2 | `test_all_nav_buttons_present` | ① `.nav button.count() >= 5` ② texts 里有 Dashboard + Rules + About（**只校验这三个**）③ Dashboard 第一个按钮有 `act` class | draft 声称"6 个按钮全部可见且可点击"——可点击未校验；只验了 3 个文本 | **REQ-F-012 / ACC-P13-008**（console 展示 matched rule / configuration / statistics / topology——前版错标 REQ-F-045）|
| 3 | `test_status_bar_renders` | 8 个 DOM id 各存在一个：`aDot, aSt, aInst, aVer, aUp, aCal, aAct, aTgt` | draft 写了"Load"字段——实际没有 Load id | —（`AGENT.md` §4.4 console standard 健康检查初始态）|
| 4 | `test_both_websockets_connect` | `#wsEv` + `#wsLd` 的 inner_text 含 "live"，轮询 ≤ 10s 成功 | 一致 | **REQ-F-042 + REQ-F-044 / ACC-P12-005 + ACC-P12-007**（两个 AS per-call event stream + generator pool_status_update）|
| 5 | `test_initial_dashboard_controls_state` | ① `#btnStop.is_disabled()` 为 True ② `#gaugeVal.inner_text` 以 `"0 /"` 开头 | draft 声称验证 btnStart enabled——代码没验 btnStart | **REQ-F-049 / ACC-P13-005**（generator 控件初始态）|

### 3.2 TestNavigation（8 个）—— SPA 视图切换

> **HY4 修正**：全仓库 grep `REQ-F-051` 只命中本计划旧版（L178 "test_screening_view_renders" 那行），是凭空造的 ID，已删。所有 SPA 视图切换归 **REQ-F-012 / ACC-P13-008** 范围。

| # | 测试名 | 核心断言（代码实际） | 备注 | REQ / ACC（HY4 修正） |
|---|--------|---------------------|------|----------------------|
| 6 | `test_call_trace_view_renders` | ① 点 Call Trace → `#vw-call-trace.classList.contains('act')` True ② `.nav` count == 1（没丢）③ `.nav button[data-v="call-trace"].classList.contains('act')` | **不**断言其他视图不可见（只 #13 部分覆盖）。选择器是 `#vw-*` id + `classList.contains('act')`，不是 draft 写的 `.vw-*` class | **REQ-F-012 / ACC-P13-008** |
| 7 | `test_rules_view_renders_and_has_content` | ① `#vw-rules.classList.contains('act')` ② `#rulesCard.inner_text` 非空 | draft 声称"找到 ≥ 3 条规则卡片 `.rule-card`"——实际只验 inner_text 非空，无条数、无 `.rule-card` 选择器 | **REQ-F-012 / ACC-P13-008**（前版错标 REQ-F-050 Chart.js vendoring）|
| 8 | `test_screening_view_renders` | ① `#vw-screening.classList.contains('act')` ② `#scrCard.count() == 1` | 一致（draft 没提 #scrCard）| **REQ-F-012 / ACC-P13-008**（**前版凭空造了 REQ-F-051——已删除**）|
| 9 | `test_statistics_view_renders` | ① `#vw-statistics.classList.contains('act')` ② `#statsCard.count() == 1` | 一致 | **REQ-F-012 / ACC-P13-008** |
| 10 | `test_about_view_renders` | ① `#vw-about.classList.contains('act')` ② inner_text 含 `"third-party"` | 一致 | **REQ-F-012 / ACC-P13-008** |
| 11 | `test_nav_stays_visible_after_each_view` | 遍历 5 个非 dashboard 视图 → 每步 `.nav.count() == 1` + 当前按钮有 `act` | 不验证其他按钮的 act 状态（只验证当前点击的那个）| **REQ-F-012 / ACC-P13-008** |
| 12 | `test_round_trip_rules_to_dashboard` | ① 点 Rules → `#vw-rules.act` ② 点 Dashboard → `#vw-dashboard.style.display != "none"` + `#vw-rules.classList.contains('act') == False` | draft 写的是"`.centre` 恢复可见"——代码用 `#vw-dashboard.style.display` 检查（两者等价，但实现更精确）| **REQ-F-012 / ACC-P13-008** |
| 13 | `test_all_views_then_back_to_dashboard` | 遍历 5 个视图 → 每个 `#vw-{view}.act` 在结束后为 False → `#vw-dashboard.style.display != "none"` | 这是唯一验证"其他视图不可见"的测试 | **REQ-F-012 / ACC-P13-008** |

### 3.3 TestGeneratorLifecycle（4 个）—— Start/Stop 生命周期

> **HY4 M-4 代码已修（2026-09-23）**：#17 用 `_put_config()`（stdlib urllib）+ try/finally 恢复原配置，不再用 `requests`、不再泄漏 session 状态。

| # | 测试名 | 核心断言（代码实际） | 备注 | REQ / ACC（HY4 修正） |
|---|--------|---------------------|------|----------------------|
| 14 | `test_start_button_hits_rest_endpoint` | **点 #btnStart → page.wait_for_timeout(500) → 直接 `_gen_status("/load/status")` 验证 `running=True`** | draft 声称"监听浏览器 response 事件"——**实际没有任何 response 监听**，是点了按钮后直接 REST 轮询 | **REQ-F-049 / ACC-P13-005** ✔ |
| 15 | `test_active_calls_rise_after_start` | Start → deadline 20s 轮询 REST `/load/status` → 看到 `active_calls > 0`（用 `ever_had` boolean，不假设峰值）| 一致 | **REQ-F-049 / ACC-P13-005** ✔ |
| 16 | `test_stop_button_drains_active_to_zero` | Stop → deadline 15s → 同时满足 `running=False` 且 `active_calls=0` | 一致 | **REQ-F-049 / ACC-P13-005** ✔ |
| 17 | `test_console_gauge_rises_then_falls_with_generator` | 4 阶段：① **try 前** `orig_cfg = _gen_status()` 存原配置 → `_put_config` 禁 T4 + 改 call_rate ② generator REST active_calls > 0 至少一次 ③ console `#gaugeVal.inner_text` 非零至少一次 ④ Stop → 两个 drain 断言 → **finally** 恢复 `_put_config(gen, orig_cfg_body)` | 前版用 `requests.put` + try/except 吞异常 + **不恢复配置**（M-4 blocker）——已修 | **REQ-F-047 + REQ-F-049 / ACC-P13-003 + ACC-P13-005**（gauge=REQ-F-047，generator 控件=REQ-F-049；**slider → call_rate → binding-constraint 闭环未覆盖**，见 §5.1 R3-P0-1）|

### 3.4 TestDashboardLive（5 个）—— 实时图表

> 图表用 `_read_chart()` helper（L76-84），走 `Chart.getChart(el)` 读，不是 draft 里的 `el.__chart__`。
> **阈值推导口径**（R2-P2-2）：折线 chart 约 500ms 推一个点，wait 6s 理论 12 点；≥4 给 WS 抖动 + 首次连接延迟 3× 容错系数。trace 面板同理：wait 8s，每 call 产生 3-5 条 trace，≥3 允许短 calls + pool_feed bursty 导致的低值时段。
> **HY4 P0-3 代码已修**：#22 文件头 `import pytest` 已加，`pytest.skip` 不再 NameError。

| # | 测试名 | 核心断言（代码实际） | 与 draft 差异 / 阈值推导 | REQ / ACC（HY4 修正） |
|---|--------|---------------------|--------------------------|----------------------|
| 18 | `test_line_chart_accumulates_points` | Start → wait 6s → `Chart.getChart(lineChart).data.labels.length >= 4` | draft 写 `>= 6`，实际代码是 `>= 4`。**推导**：6s ÷ 0.5s/point = 12 理论点 × 0.33 容错 = 4 | **REQ-F-045 / ACC-P13-001**（**前版错标 REQ-F-046 饼图**——折线图是 REQ-F-045）|
| 19 | `test_pie_chart_has_nonzero_segments` | Start → wait 8s → `sum(pieChart.data.datasets[0].data) >= 3` | 一致。**推导**：8s 至少 1 D2 call 完成 + 部分 D1 reject | **REQ-F-046 / ACC-P13-002** ✔（环形图是 REQ-F-046）|
| 20 | `test_topology_svg_links_change_on_active` | ① 读 idle 态 `#l1.getAttribute('stroke-width')` ② Start → deadline 20s 轮询 → 找到 `active_sw > idle_sw + 0.1` ③ 否则 assert False + dump console 内部 state (activeCalls, counters, topoVal, l1_sw) | 文档 4.3 节描述"Math.max(activeCalls, counters.active, totalTraffic)"准确。draft §3 声称"> 1"——实际是浮点比较 `active_sw > idle_sw + 0.1`（idle 基线通常≈1.0，比较增量 0.1）| **REQ-F-048 / ACC-P13-004** ✔（颜色未覆盖，见 §5.1）|
| 21 | `test_trace_panel_accumulates_call_records` | Start → wait 8s → `#tlist .ti` count `>= 3` | draft 写 `>= 5`，实际代码是 `>= 3`。**推导**：wait 8s，每 call 产生 3-5 条 trace entry × bursty factor 0.5 = 3 下限 | **REQ-F-042 / ACC-P12-005**（**前版错标 REQ-F-047 gauge**——trace 是 AS per-call event stream）|
| 22 | `test_trace_filter_narrows_list` | ① 取 `total_before = #tlist .ti count` ② **若 0 → `pytest.skip()`** ③ 输入 `"zzzzzzzNoMatchzzzzz"`（必然不匹配的字符串）④ assert `after_nomatch <= total_before` | **⚠️ smoke-only**（R2-P2-1）：断言在 filter 完全失效时也会通过。**已修** P0-3（import pytest），但 `pytest.skip()` 是否实际被调用仍是随机的（generator 是否够活跃产生 ≥1 条 trace）。强化路径：改首条 trace 的 Call-ID 片段作为过滤词，断言 `after == 1` + `total_before > 1` | **REQ-F-042 / ACC-P12-005** ✔ |

### 3.5 TestAsRestEndpoints（4 个）—— AS 后端 REST API

| # | 测试名 | 核心断言 | 为什么重要 | REQ / ACC（HY4 修正） |
|---|--------|----------|------------|----------------------|
| 23 | `test_healthz` | `GET /healthz` → 有 `status`, `version`, `uptime_seconds` | 基本健康检查 | ——（基础设施）|
| 24 | `test_metrics` | `GET /api/v1/metrics` → 有 `counters`, `peer_status`, `calls_by_disposition` | metrics 数据结构 | **REQ-F-042 / ACC-P12-005** ✔ |
| 25 | `test_rules` | `GET /api/v1/rules` → 有 `rules` 列表，长度 ≥ 3，每条有 `rule_id`, `priority`, `action` | 规则列表加载（Dashboard #7 的数据源）| **—（数据源，同 REQ-F-012 范围）**（**前版错标 REQ-F-050——REQ-F-050 是 Chart.js vendoring**）|
| 26 | `test_traces_list_has_calls_key` | `GET /api/v1/traces` → 返回 dict，有 `"calls"` 键（不是裸 list）| traces API 数据结构正确 | **REQ-F-042 / ACC-P12-005**（**前版错标 REQ-F-047 gauge**——trace 是 AS event stream）|

### 3.6 TestConcurrentViewSwitchAndGenerator（2 个）—— 并发场景

| # | 测试名 | 核心断言 | 为什么重要 | REQ / ACC（HY4 修正） |
|---|--------|----------|------------|----------------------|
| 27 | `test_generator_runs_survives_navigation` | Start generator → 遍历 5 个视图 → 回 Dashboard → generator 仍 running | View 切换不中断 WS；核心语义是 generator 持续运行 + 视图切换存活 | **REQ-F-049 / ACC-P13-005**（前版错标 REQ-F-042——那是 AS event stream）|
| 28 | `test_stop_after_view_hops_resets` | 同上 + Stop → drain 到 0 | 并发 Stop 正常 | **REQ-F-049 / ACC-P13-005** ✔ |

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

> **命名漂移**（HY4 M-7）：
> - `phase3-plan.md` 写 `/ws/events` 和 `/ws/load`，实际实现是 `/ws/p12/events` 和 `/ws/pool`（`src/console/main.py` L223-224）
> - **`docs/acceptance/criteria.md` ACC-P12-007** 同样写 `/ws/load`（不是 `/ws/pool`）——仓库级漂移。本文档 2.1 / 2.3 / 4.2 均已对齐到实际端点名，但 criteria.md / phase3-plan 未同步

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

### 5.1 相对于 phase3-plan.md 的覆盖缺口（review P1-1 + R2-P1-1）

`docs/phase3-plan.md` P13 Stage 4 对 E2E 有明确要求，本 28 测试**未覆盖**的项：

| phase3-plan 出处 | 要求 | 本 28 测试现状 |
|---|---|---|
| §P13 Stage 4 E2E step (5)(6) + §6 风险表第 4 行（High） | "slide to 5 → verify chart drops"——target concurrency slider → REST `/load/config` → pool → WS → gauge chart **完整闭环** | 本文件无任何 slider E2E。#17 用 `requests.put /load/config` 禁用 T4 作为测试前置，但**不**断言 slider UI → REST → pool 响应链路。phase3-plan 将其列为影响 High 风险 |
| **D6 Little's Law 教育性设计 + ACC-P13-005**（R2-P1-1） | 双滑块（target concurrency 0-20 + call rate 0.1-10）的 Little's Law 交互：改 call_rate → `/load/status.binding_constraint` 从 "concurrency" 翻转为 "rate"；binding-constraint 指示器是 ADR-0013 的标志性演示特性 | **零覆盖**。#17 的 `PUT /load/config` 只改 `target_concurrency` + `enabled_call_types`，**从不碰 `call_rate`**。binding_constraint 字段（`tools/call_load_generator.py` L252）从未在 28 个测试中断言 |
| REQ-F-049 | call type toggles E2E | 无 |
| REQ-F-048 / §P13 Stage 3 step 7 | 拓扑按 hop 颜色（绿/红/橙） | 本文件只测 `#l1 stroke-width`，颜色（stroke CSS var）未测 |
| §P13 "chained demo compatibility" / D8 | 拓扑为固定四节点 `S-SBC → anti-fraud → translation → S-SBC ret`；P14 起按模式淡化未参与节点（simple 淡化 anti-fraud，fraud 淡化 translation），chained 换用含 iFC + UAS 的图 | conftest 只起 1 个 AS（translation），无 anti-fraud 进程。拓扑最左两跳在 E2E 栈里不存在。**chained 拓扑覆盖在 `test_chained_call_flows.py`（非浏览器 E2E）和 `test_chained_topology.py`（integration），console dashboard 的拓扑图渲染链式场景未测** |

→ **建议**（按优先级）：
1. **最高优先**（R3-P0-1 / ADR-0013 教育性演示）：补一个 **REST 级 E2E**（不需要浏览器断言）来验证 `binding_constraint` 翻转。**配方方向必须按下面写**——`compute_binding_constraint()`（generator L238）判定是 `call_rate × AVG_DURATION_SECONDS(10.4) >= target_concurrency → "concurrency"`，**`call_rate` 越大越倾向于 "concurrency"**，反之才是 "rate"（HY4 B-1 指出原版方向写反）：

   | 目标 | PUT 到 `/load/config` 的 body | 判定依据 |
   |---|---|---|
   | `"rate"` 绑定 | `{target_concurrency: 10, call_rate: 0.1, ...}` | `0.1 × 10.4 = 1.04 < 10` → 回 `"rate"` |
   | `"concurrency"` 绑定 | `{target_concurrency: 10, call_rate: 2.0, ...}` | `2.0 × 10.4 = 20.8 >= 10` → 回 `"concurrency"` |

   **重要**：PUT `/load/config` 的响应体**不含** `binding_constraint` 字段（generator L776 只 echo config），所以新测试必须 PUT 后再 **GET `/load/status`** 读取该字段。建议复用已有的 `_put_config` helper + 新增 `_gen_status` 断言，约 15 行。验收口径：在 `test_call_pool.py` L198-221 的现有语义下稳定变绿（`target=10, rate=10.0 → "concurrency"`；`target=50, rate=1.0 → "rate"`）。

2. **次优先**：补 slider 改 target_concurrency → gauge/target 读数随 pool_status_update 变化闭环测试。

3. **DOM 唯一性**（R3-P1-2 / M-3 #1）：每个 `#vw-{view}` 必须全局唯一——当前 `locator.evaluate` 只作用于首个匹配元素，若未来 `.vw` 又被复制（正是 B3 历史根因），28 个测试照样全绿。建议补一条：`assert page.locator("#vw-rules").count() == 1`（可参数化到 5 个视图），约 6 行。

4. **WS 离线重连**（R3-P1-2 / M-3 #2）：console JS 实现了 `ewsEv()` / `ewsLd()`（console L423 / L445）3s 重连 + `fh()` catch 分支把 `#aSt` 置 `"unreachable"`。可用 `page.context().set_offline(True/False)` 做纯前端测试（零额外进程成本），覆盖"演示中抖网会不会白屏"这个真实评审场景。

5. 其余缺口在 `docs/testing/e2e-call-flows-plan.md` 和 `docs/testing/integration-plan.md` 有覆盖，不再此处重列。

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

---

### HY4 发现但超出 E2E 范围的仓库级问题（R3-P1-4 / R3-P2-2）

| 问题 | 位置 | 影响 | 建议 |
|------|------|------|------|
| **`AVG_DURATION_SECONDS` 9.5 vs 10.4 不一致** | 代码实际算术 `0.30×2.5 + 0.50×11.5 + 0.15×25 + 0.05×3 = 10.4`（generator L105 注释却写 `# = 9.5`）；且 **ADR-0013 L79、HLD §12.4、unit-plan.md、`test_call_pool.py` L200/L208 注释、`test_duration_model_avg_duration_constant` 单测** 四处均写 9.5 | ADR-0013 的 Little's Law 教育性演示（R3-P0-1 新 binding-constraint 测试的数学前提）全部引用错常量 | **这是 maintainer 裁决项**：要么改五处文档注释 + 代码注释到 10.4 并改单测为断言字面量；要么改 `DurationModel.MIDPOINTS/WEIGHTS` 真的让算术出 9.5（需要调整权重或 midpoint 值）。**不能让 plan / code / ADR / HLD / 单测五处互相打架**——`compute_binding_constraint()` 的数学前提必须唯一 |
| **criteria.md ACC-P12-007 `/ws/load` 漂移** | `docs/acceptance/criteria.md` 写 `/ws/load` 但实际是 `/ws/pool`（`src/console/main.py` L224） | criteria 验证命令引用错端点；评审照 criteria.md 念会找不着接口 | 维护者同步 criteria.md + phase3-plan.md 到实际端点 |

### HY4 已完成代码修复（2026-09-23 commit be05d69）

| 项 | 改动 | 验收 |
|---|------|------|
| M-4 | 去 `requests` + 新 `_put_config()`（urllib） + #17 try/finally 恢复 config | 28/28 顺序跑 vs `-k test_console_gauge_rises...` 一致 |
| P0-3 | 加 `import pytest` + `pytestmark = pytest.mark.e2e` | `make e2e` 收集 37 测试不静默跳过 |
| M-5 + R2-P2-3/R2-P2-4 | `_reset_gen` 分不可达 vs 超时 + 删 conftest 死副本 + 4 进程日志落 per-session tmpdir | 手动 kill generator → pytest.fail 清晰；无 `/tmp/e2e-*` 残留 |
