# Phase 3 交付审计 · 未完成清单

**日期**: 2026-09-24  
**作者**: live session audit（非代码生成）  
**分支**: `phase3`  
**基准提交**: `a5ea2ee`（用户提交：41 文件，`CoreUas`→`ReturnUas` 重命名 + 全文档清理 + simple SVG 拓扑重画 + 方案 C 连线/节点染色拆分）  
**当前未提交改动**: `src/console/main.py`, `config/routing_rules.yaml`, `.env.example`（见 §6）

---

## 0. 为什么写这个文档

roadmap 上 P12/P13/P14 都标着 `[Status: Done]`。但在 2026-09-24 的 live demo 里，连续撞到以下 bug：

1. AS 启动失败（`ModuleNotFoundError: as_platform.route_header`）
2. 前端硬编码 `192.168.31.239:8080`，Windows 浏览器跨 OS 访问全断
3. URL 自适应正则把端口号吃了（所有 fetch 走默认 80）
4. Network Topology 连线 err→全局染色（608 是 AS 内部决策，不是链路状态）
5. 两个 slider 撑爆侧边栏，水平拖动条
6. Simple 拓扑画了不存在的 Anti-fraud 节点
7. Statistics 视图只渲染 AS metrics API 的 2/6 字段
8. Live Trace 按 Call-ID 过滤后只见一行（``call_started`` 曾以 ``call_id='-'`` 发出，与 routed/ended 的 trunk Call-ID 不一致）

全部是 "Done" 标签掩盖的**没做 / 做错 / 数据断链**的问题。本文档列出所有遗留项，每条给**文件路径 + 行号 + API 返回证据 + 建议改动**，让接手者能直接动手。

---

## 1. Statistics 视图 — AS metrics API 6 字段只渲染了 2 个

**严重性**: 高（UI 半成品，API 完整但前端浪费了数据）  
**位置**: `src/console/main.py:598-600`（`function rs()`）  
**触发**: 点击 nav → Statistics

### 当前代码

```javascript
// src/console/main.py:598-600
function rs(){if(!md)return;var c=E("statsCard");
  c.innerHTML='<p style="color:var(--acc);font-size:14px;font-weight:700;margin-bottom:8px">'+(md.calls_total||0)+' total calls</p>'+
  '<p style="color:var(--mut);font-size:12px">disposition: '+JSON.stringify(md.calls_by_disposition||{})+'</p>'}
```

### AS `/api/v1/metrics` 实际返回（curl 证据）

```json
{
  "calls_total": 58,
  "calls_by_disposition": {"completed":43,"no_match":12},
  "errors_by_code": {"AS-ROUTE-001":12},
  "rule_hits": {"R-MOB-CM-40":25,"R-INTL-80":11,"R-FIX-NAT-70":10},
  "peer_status": {
    "127.0.0.1:5062:trunk": "reachable",
    "s-sbc-primary:127.0.0.1:5061": "reachable",
    "intl-gateway-primary:127.0.0.1:5061": "reachable"
  },
  "counters": {}
}
```

### 渲染缺口

| 字段 | 前端渲染？ | 建议渲染方式 |
|---|---|---|
| `calls_total` | ✅ | 保留 |
| `calls_by_disposition` | ✅（但 JSON.stringify） | 改为 disposition→中文 label 映射 + 计数 |
| `errors_by_code` | ❌ **没渲染** | 表格：错误码 → 计数；可用红色 row 高亮 |
| `rule_hits` | ❌ **没渲染** | 表格：rule_id → 命中数；和 Rules 视图联动（点击跳 Rules） |
| `peer_status` | ❌ **没渲染** | 表格：peer → reachable 状态圆点（绿/灰/红） |
| `counters` | ❌（空 dict） | Dashboard 用了 WS pool_status，stats view 不需要 |

### 相关代码位置

| 项 | 路径 |
|---|---|
| 点击 Statistics 时触发 | `main.py:572` — `if(v==="statistics"){if(!md)fm();else rs()}` |
| `fm()` fetch metrics + 存 `md` | `main.py:551-552` — `async function fm() { md = await fetch(AS_URL+"/api/v1/metrics") }` |
| `rs()` 渲染（要改的） | `main.py:598-600` |
| E2E 测试只断言 statsCard 存在 | `tests/e2e/test_console_dashboard.py` `test_statistics_view_renders` — 只验 `count==1`，不验内容 |

### 建议改动范围

- 只改 `rs()` 函数（约 30-40 行），把三段 `innerHTML` 拼接改为结构化：
  1. disposition 表格（label 映射）
  2. errors_by_code 表格（如果非空才显示）
  3. rule_hits 表格
  4. peer_status 表格（带颜色圆点）
- 不需要新 API、不需要新依赖、不需要 Chart.js（纯 HTML table + CSS 圆点）

---

## 2. Binding Constraint Indicator — Little's Law 绑定方向没显示

**严重性**: 中（ADR-0013 明确要求，Dashboard 上看不见绑定方向）  
**来源**: ADR-0013 "Two controls — Little's Law coupling"  
**位置**: `src/console/main.py` Dashboard 区域；generator API 已返回

### 后端已实现

generator `GET /load/status` 返回：

```json
{
  "target_concurrency": 10,
  "call_rate": 3.0,
  "active_calls": 10,
  "binding_constraint": "concurrency",  // ← rate | concurrency
  "theoretical_concurrency": 28.5,
  ...
}
```

generator 内部逻辑（`call_load_generator.py` 的 `binding_constraint` 字段）：
- `call_rate × avg_duration (≈9.5s) >= target_concurrency` → `"concurrency"`（rate 再高没用，卡在并发）
- 否则 → `"rate"`（没喂饱，呼叫生成速度才是瓶颈）

### 前端没显示

Dashboard 有 Target slider + Call rate slider + gauge + 折线图 + 饼图 + 拓扑 —— **没有一行文字说 "当前是 rate binding 还是 concurrency binding"**。

### ADR-0013 原文（95-98 行）

> **Binding constraint indicator on console (P13).** The console shows which control is currently limiting. This is not decoration — it explains why the pool is at its current level, which makes the demo comprehensible to someone who does not know Little's Law going in.

### 建议改动

- `onPoolStatus()` 里从 `s.binding_constraint` 取值
- Dashboard gauge 下方加一行小 label：`binding: concurrency (rate×duration=28.5, target=10)` 或 `binding: rate (rate×duration=4.7, target=10)`
- 位置：Dashboard gauge 卡片下方；或 gauge 数字旁边一个小 tag

---

## 3. Dashboard 没渲染 rule_hits / errors_by_code

**严重性**: 中（Dashboard 只有实时图，缺 AS 实例的累计错误/规则命中视图）  
**背景**: P13 Enhanced Console 把所有增强做在了 Dashboard，但只覆盖了 generator WS 推送的实时数据。AS metrics API 里的 `rule_hits` / `errors_by_code` 是**自进程启动以来的累计**，Dashboard 没显示。

### 和 item 1 的关系

Statistics 视图**和 Dashboard 可以各有侧重**：
- Dashboard = 实时动态（WS 驱动，~1s 刷新）
- Statistics = 汇总快照（REST metrics，点击进入时 fetch 一次）

但 Dashboard 也可以加一个**小卡片**显示最近的 rule hit / error code 快照（每 10s 轮询一次 metrics），和实时 WS 并存。

### 建议

轻量方案：Dashboard gauge 卡片旁边或下方，加一个 `AS summary` 小卡片显示：
- `calls_total`（累计）
- `top rule hit`（rule_id + count）
- `errors`（非空时红色显示）
- 点击进入 Statistics 视图看完整表格

---

## 4. generator topology 参数校验 — `put_config_rejects_f_types_in_simple_topology` 测试覆盖但 UI gate 不完美

**严重性**: 低（测试通过、服务端校验到位；UI 上 toggle 的禁用逻辑可以再确认）  
**位置**: `main.py:400-420` `applyToggleGating()`

### 现状

- 选 `simple` topology → UI 禁用 F1-F4 toggle（grey out）
- 选 `fraud` topology → UI 禁用 T1-T6 toggle
- 服务端 `PUT /load/config` 有校验，跨类型 rejected 返回 HTTP 400
- 但 E2E 没专门测"UI toggle 禁用 + 用户强启 toggle + 服务端 reject → 恢复禁用态"的完整闭环

### 建议

先确认服务端校验是否到位（`test_put_config_rejects_f_types_in_simple_topology` 通过了），UI gate 是装饰层。

---

## 5. Phase 3 "Done" 标签的其他需要澄清的项

| 项 | 现状 | 说明 |
|---|---|---|
| dual AS WS（fraud + translation） | ✅ P14 已实现 | `--fraud-api-url` 开启第二个 WS + 第二个健康状态点 |
| chained topology AS-1 → AS-2 iFC 编排 | ✅ ADR-0014 已落地 | generator 不再直接 AS-to-AS，由 ims_mock orchestrator 编排 |
| console 模式感知 | ✅ | `setTopologyMode()` 自动切换 simple/chained SVG |
| AS metrics API 完整 | ✅（6 字段） | 但前端消费不完（item 1, 3） |
| generator pool_status_update WS | ✅ | Dashboard 主要数据源 |
| console → generator REST poll 兜底 | ✅（本轮修） | `pollLd()` + `setInterval` 解决 WS 被代理掐断 |
| topoSimple SVG（三节点方案 C） | ✅（本轮改） | 2026-09-24 live session 重画 |
| URL 自适应 | ✅（本轮改） | `location.hostname` 替换注入 IP，正则吞端口 bug 已修 |
| CoreUas → ReturnUas | ✅（用户 a5ea2ee） | 全仓重命名，零行为变化 |
| route_header.py 本地化 | ✅（本轮改） | 严格遵守 REQ-NF-027，不修改 as_platform repo |
| simple SVG 文字 "core" → "S-SBC ret" | ✅（用户 a5ea2ee） | 语义对齐 |

---

## 6. 当前未提交改动（接手者注意）

```
.gitignore
.env.example                                       改动
config/routing_rules.yaml                         大改动（端口对齐 + 规则完善）
config/routing_rules.yaml.bak                     ← 这个 .bak 可以删掉
src/console/main.py                               本轮改：URL 自适应、topoSimple 重画、paintNodes、layout min-width
```

### main.py 具体改了什么（本轮，未提交）

| 段 | 改动 |
|---|---|
| JS 变量区 (L249-253) | `AS_URL` / `LD_URL` 正则修正：`replace(/:\/\/[^:/]+/, ...)` 保留端口 |
| CSS .grid (L60) | `grid-template-columns: 200px 1fr 280px` + `min-width:0; overflow:hidden` |
| CSS .nav/.centre/.right (L61,68,76) | 全部加 `min-width:0` |
| CSS .ctl-row (L96-99) | label 80→70，range `min-width:0`，`.val flex-shrink:0` |
| SVG #topoSimple (L201-210) | 三节点：`[S-SBC] ─l1─▶ [Translation AS] ─l2─▶ [S-SBC ret]`；删除 `nFraud`，`nTrans` 改名，`l3` 删除 |
| SVG #topoChained (L218,224) | 加 `id="cAS1"` / `id="cAS2"`（给 paintNodes 用） |
| `topoIntensity()` (L365-377) | 拆分 `linkColor`（只 active/idle）+ `nodeStroke`（err/warn/ok） |
| 新增 `paintNodes()` (L386-391) | 给 AS 节点染 stroke |
| `setTopologyMode()` (L392-398) | 删除 nFraud/nTrans opacity 切换（三节点不需要 dim） |
| `updateTopology()` (L423-435) | simple: `paintLinks(["l1","l2"])` + `paintNodes(["nTrans"], nodeStroke)`；chained: `paintLinks(["cl1..cl5"])` + `paintNodes(["cAS1","cAS2"], nodeStroke)` |

### routing_rules.yaml 改动（未提交）

next_hop 端口从 15061/15062 统一为 5061（实际 demo 值）；端口注释里的 15061→5061，和 demo 运行时 rewrite 一致。

### .env.example 改动（未提交）

同上端口对齐。

### 接手者第一步

```bash
git status                     # 确认当前 state
git diff src/console/main.py   # 确认 main.py 改动细节
uv run pytest -q               # 确认测试全绿再继续
```

---

## 7. Live Trace Call-ID 过滤 — P12 ``call_started`` 用了 ``"-"``（已修 + 测试分层）

**严重性**: 高（用户按 Call-ID 过滤只见 ``call_routed`` 一行，lifecycle 看起来断了）  
**根因**: ``CallController.__init__`` 时 ``call_id=='-'`` 就 emit ``call_started``；``call_routed`` / ``call_ended`` 用的是 ``recv_request`` 后的真实 Call-ID  
**位置**: ``src/as_app/call_controller.py``, ``src/anti_fraud_as/call_controller.py``（P12 路径，**不是** Phase 1 ``TraceRecorder``，**不是** load generator 专属）

### 修复

``call_started`` 移到 ``super().recv_request()`` 之后，与 routed/ended 共用 trunk Call-ID。

### 测试分层（勿只写在 E2E plan）

| 层 | 文件 | 断言 |
|---|---|---|
| **unit** | ``tests/unit/test_p12_call_controller.py`` | 构造时不 emit；``recv_request`` 后用 trunk Call-ID |
| **integration** | ``tests/integration/test_p12_call_events.py`` | 单通 ``trunk_pair`` + ``start_internal_api``，broadcast 捕获 started+routed+ended 同一 ``call_id`` |
| **e2e** | ``tests/e2e/test_console_dashboard.py`` #43 | 浏览器 ``#filt`` 过滤后 ≥3 行（UI 附加证据）|

**状态**: 代码已修；unit + integration + E2E 计划已补（2026-09-24）

---

## 8. 已知设计决策（接手者别推翻）

| 决策 | 理由 | 来源 |
|---|---|---|
| simple 拓扑 **S-SBC → Translation AS → S-SBC ret**（三节点） | 运营网络视角，不含 generator；simple 模式 anti-fraud 不启动 | 本轮 live session 确认 |
| chained 拓扑保留 6 节点 + iFC | ADR-0014 | ADR-0015 |
| 连线只 active/idle，AS 节点 stroke 承载 err/warn | err/warn 是 AS 内部决策，不是链路状态 | 本轮方案 C |
| CoreUas 改为 ReturnUas | 真实角色是 S-SBC return side，不是"core" | 用户 a5ea2ee |
| `route_header.py` 本地化到 as_app / anti_fraud_as | REQ-NF-027 禁止 Phase 3 修改 as_platform | REQ-NF-027 |
| URL 自适应 `location.hostname` | WSL → Windows 跨 OS 访问必须 | 本轮 bug |

---

## 9. 下一步优先级建议

| P | 项 | 理由 | 状态 |
|---|---|---|---|
| 1 | Statistics 视图补全 4 个缺失字段（item 1） | 最明显的"Done 标签下的半成品"，20 行内改完 | **Done** — `rs()` 渲染 disposition / errors / rule_hits / peer_status 表格 |
| 2 | Binding constraint indicator 放到 Dashboard（item 2） | generator 后端实现了但前端没消费，Little's Law 是 P13 demo 核心叙事 | **Done** — `#bindInd` 在 `onPoolStatus` / `pollLd` 更新 |
| 3 | Dashboard AS summary 小卡片（item 3） | 累计 metrics 与实时 WS 并存 | **Done** — `#asSummary` 每 3s 随 `fm()` 刷新，链到 Statistics |
| 4 | 提交本轮改动 | 清理未提交 state，便于跨机器 | 待 maintainer |
| 5 | 在另一台机器上跑完整 demo 流程（`phase3-demo.sh simple` + Windows 浏览器） | 确认所有跨 OS 场景修复生效 | 待验证 |
| 6 | 全量跑 Playwright E2E（`uv run pytest tests/e2e/test_console_dashboard.py -v`） | 本轮 main.py 改了但 Playwright 全量没跑过 | **已补计划+用例** — `docs/testing/e2e-playwright-plan.md` §3.7–3.9 新增 6 测（#37–42）；#43 + integration/unit P12 Call-ID 测试 |

---

## 10. 测试结果快照（2026-09-24 live session）

```bash
# Console integration — 7 passed ✅
uv run pytest tests/integration/test_console.py -q

# 全量 suite — 307+ passed ✅（`a5ea2ee` 提交后跑过）
uv run pytest -q

# ruff — All checks passed ✅
uv run ruff check .
```
