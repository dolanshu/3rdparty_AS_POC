# Phase 3 plan — Call Load capability + Enhanced Console

- **Status:** plan approved by maintainer, 2026-09-21
- **Document owner:** project maintainer
- **Purpose:** This document is the single source of truth for Phase 3. Every decision,
  work item, and acceptance criterion for Phase 3 is recorded here. Questions about
  "why are we doing X" or "what does this item deliver" should be answered here first.
- **Companion document:** `docs/post-phase2-directions.md` records the research that
  informed Phase 3's scope selection (Part A) and the decision record that led to this
  plan (Part B). This plan is the execution document; the directions document is the
  decision document.

---

## 1. Purpose and scope of this document

Phase 2 (P8–P11) delivered two AS use cases (number translation, anti-fraud), a chained
demo, a capacity probe, a platform library extraction, and TLS + Redis + capacity harness
verification. `as_platform` is published, CI is green, this repository is `v0.9.0`.

Phase 3's purpose is **display capability**. Phase 1/2 validated single-call functional
correctness — every demo ran one SIP call at a time, walking the reviewer through its
lifecycles manually. Phase 3 demonstrates **the AS handles N concurrent SIP calls, of
mixed types, mixed durations, independent lifecycles** — and it shows that capability
on a real-time operations dashboard that replaces the hand-run demo script.

This document records:
1. Why this was selected as Phase 3 over the earlier revision-1 direction (D3 Session
   Registry + B3 DNS SRV) — §2 strategic decisions.
2. The exact work sequence — P12 Call Load backend, then P13 Enhanced Console frontend
   — §3.
3. How the items are executed (pipeline, branches, review gates) — §4 and §5.

This document does **not** record rejected directions in detail; see the companion
document's Part A and Part B §9.2 for those.

---

## 2. Strategic decisions

### D1 — Phase 3 purpose: demonstrate multi-call concurrency capability

**Decision.** Phase 3's priority is to demonstrate that the AS architecture already
supports multi-call concurrency — CallController per-instance isolation (each call has
its own `self.call_id`, `self._incoming`, `self._outgoing`) means nothing changes in the
architecture. Phase 1/2 never exercised this; Phase 3 is the first time we deliberately
run N calls in parallel and show them progressing independently.

**Rationale.** `phase2-plan.md` D1 ("portfolio piece, not a product") says display value
outranks functional completeness. Every reviewer of Phase 1/2 saw one call at a time.
"15 calls of mixed types all progressing through their own lifecycles simultaneously"
is a more credible capability statement than any platform-layer abstraction.

**Consequence.** No changes to `as_platform` library are required. All Phase 3 work is
in this repository. This is the first phase where both items (P12 and P13) are
application-level — not platform-level.

### D2 — AS architecture unchanged; CallController isolation already works

**Decision.** Call Load will **validate** concurrent-call isolation under load, not
**modify** the AS architecture. P9.5 showed that the `ED2` event loop gap grows at 64
concurrent calls when all AS instances share one Python interpreter — but Phase 3 runs
each AS as its own process (各自独立的 ED2 loop), so per-AS bottleneck is less severe.

**Rationale.** The architecture already does the right thing: each incoming INVITE gets
one CallController, no shared mutable state between controllers, only the `ED2` loop is
shared per-process. The only unknowns are at the edges (P8a timer population under
concurrent load, whether one controller's timer cancel can reach another's) — not in the
core model.

**Exit condition for P12.** Concurrent-run tests demonstrate: (a) each controller
lifecycle completes independently (call 1's BYE does not terminate call 2's dialog),
(b) timer cleanup (P8a) does not cross-contaminate, (c) the console Call Trace view
correctly shows all N calls simultaneously.

### D3 — Supersede D10's "no benchmark numbers" with explicit boundary

**Decision.** Phase 2 plan D10's prohibition ("no calls-per-second and no latency figure
may be published") applies to **written documentation committed to the repository**
(README, CHANGELOG, demo script prose). It does **not** apply to **live demo artefacts**:
console real-time displays, probe stdout during a demo run, or reviewer-observed
phenomena.

**Boundary (in writing):**

| Location | Permitted? | Example |
|----------|-----------|---------|
| README.md | No headline numbers | No "本 AS 支持 X QPS" |
| CHANGELOG.md | No numbers | No "capacity improved to N" |
| demo-script.md | Describe the *probe approach*, not results | "we run the interactive load generator at the reviewer's chosen target concurrency" — the script doesn't predict results |
| Console live display | Yes | "当前活跃 call 数 = 12" (实时，随每次运行变化) |
| Demo run stdout | Yes | Load generator output during a reviewer-run demo |

**Consequence.** No documentation change except this plan and the directions document.
Demo scripts will be rewritten to frame the load generator's numbers as interactive —
reviewers choose the target, see what happens, and judge capability themselves.

### D4 — Amend AGENT.md §4.4: vendored third-party frontend libraries permitted

**Decision.** AGENT.md §4.4 is amended with a documented exception:

> **Original (Phase 2):** No third-party front-end libraries; plain HTML/CSS/JS only, so
> the demo works offline.
>
> **Amended (Phase 3):** Third-party front-end libraries are permitted when vendored into
> the repository under `src/console/static/`. No CDN-only references. Every vendored file
> must work offline without external network access. A short inventory at the top of §4.4
> lists each vendored library, its purpose, version, and where it lives.

**Rationale.** Portfolio demo quality is the overriding concern. Chart.js (~80KB,
vendored as UMD bundle) delivers real-time line charts, pie charts, and gauges in
one-third the code volume of hand-written Canvas 2D. Vendoring keeps the offline-demo
guarantee — chart rendering requires no internet.

**Affected code.** `tests/integration/test_console.py` has hardcoded checks for "no
external `<script src>` / `<link href>`". These are updated to verify that all external
references resolve to `/static/` paths within the console server.

**Inventory (as of P13 acceptance):**
| Library | Version | Purpose | Path |
|---------|---------|---------|------|
| Chart.js | 4.x (UMD bundled) | Live charts: call count line, state pie, capacity gauge | `src/console/static/chart.umd.min.js` |

### D5 — Frontend tech stack: Chart.js 4.x UMD (vendored, ~80KB) + 纯手写 CSS/SVG

**Decision.** Chart.js 4.x UMD bundled minified (~80KB) 是**唯一 vendored 的第三方库**。
capacity gauge 和动态 topology 用纯手写 SVG/CSS 实现，不需要额外依赖。

| 组件 | 实现方式 | 大小 | 理由 |
|------|---------|------|------|
| Call count 实时折线图 | Chart.js (`new Chart(ctx, {type: 'line', ...})`) | 库提供 | rolling window ~60 data points，Chart.js 轻松 handle |
| State distribution 饼图 | Chart.js (`{type: 'doughnut', ...}`) | 库提供 | 4-5 slices，Chart.js 原生支持 |
| Capacity gauge (`active/target`) | **纯 SVG** —— `<circle stroke-dasharray>` + 中心文字 | **0KB** | gauge 就是圆环进度条 + 数字；Chart.js 没有原生 gauge，插件多而乱，手写 SVG 更轻量 |
| 动态拓扑 (`SBC → anti-fraud → translation → core`) | **纯 SVG DOM** —— 4 节点 + 3 边，JS 动态更新 `stroke` 颜色和 `stroke-width` 粗细 | **0KB** | 4 节点远低于 SVG 性能瓶颈（5000+ 节点才会卡）；不需要任何 graph 库 |
| Control panel (slider + toggles) | **纯 HTML/CSS** —— `<input type="range">` + `<input type="checkbox">` | **0KB** | 不需要 Material 或 Bootstrap；dark theme + CSS variables 手写搞定 |

**为什么不是 ECharts（更大但功能更强）？** ECharts 最小 UMD ~135KB，比 Chart.js 大
50KB。ECharts 原生有 gauge 确实方便，但我们手写 SVG gauge 就能搞定。我们的三种
图表类型（折线、饼图、gauge）都是 Chart.js 的原生优势领域，ECharts 的额外能力
（地理可视化、3D、雷达图）对这个 console 完全不需要。

**为什么不是 lightweight-charts（45KB 更小）？** 只支持时间序列，不能做 pie chart
和 gauge，而这三种图表同等重要。

**Vendoring 注意事项（从经验 recall 提炼 —— 关键规则）：**

1. **必须用官方完整 UMD bundled minified 构建产物** —— 不是 stub、不是残缺文件、
   不是源码粘贴。Chart.js 4.x 正确文件是 `chart.umd.min.js`（Chart.js GitHub Releases
   的 build 产物），不是 npm install 后的其他变体。
2. **版本对齐** —— Phase 3 console 设计用 `new Chart(ctx, config)` 就是 Chart.js 4.x
   API；选 4.x bundled UMD，不要 3.x（配置结构不同）或 5.x（alpha）。
3. **同源离线 + 降级 UI** —— vendored 后 FastAPI `/static/chart.umd.min.js` 必须返回
   正确文件。离线运行测试（Docker `--network=none`）。如果 Chart.js 加载失败，所有
   图表位置显示**纯 HTML 表格**（实时读数 + 手动刷新按钮），保证即使依赖不可用也
   有可看的东西。
4. **LICENSE 伴随** —— vendored 文件旁边放 `chart.umd.min.js.LICENSE.txt`
   （Chart.js MIT license）。

**Scope.** Vendored files 在 `src/console/static/`。FastAPI 用
`StaticFiles(directory="src/console/static")` 挂载。console HTML 通过
`<script src="/static/chart.umd.min.js">` 引用。console 页面保持单页内联
（`CONSOLE_PAGE = """..."""` 字符串），没有构建步骤，没有 SPA 框架。

**Integration test update.** P13 Stage 3 把
`tests/integration/test_console.py` 的 "no external `<script src>` / `<link href>`"
硬编码检查改为：所有 `<script src>` 和 `<link href>` 必须以 `/static/` 开头
（验证同源离线）。

### D6 — Load generator architecture: interactive tool with closed-loop concurrency pool + open-loop call-rate throttle

**Decision.** A new `tools/call_load_generator.py` is the load source. The generator has
**two coupled but distinct** controls — target concurrency (pool ceiling) and call rate
(fill-speed throttle). The interaction is governed by **Little's Law** (`L = λW`, where
`L` = concurrent calls, `λ` = call rate, `W` = average call duration fixed by D7's
duration weights):

1. **Target concurrency (1-50)** — closed-loop pool ceiling. The generator maintains
   an `active_calls` counter. A tick loop (every ~500ms) tries to fill the pool to
   `target_concurrency`. **This is the primary control** — it caps the maximum
   number of simultaneous active calls regardless of anything else.

2. **Call rate (0.1-10 calls/sec)** — open-loop fill-speed throttle. Even if the pool
   is below target, the generator will not launch more than `rate` new calls per second.
   **This is the secondary control** — it limits how fast the pool refills.

**Precedence rule:** whichever constraint is more restrictive at any moment is binding.

| Condition | What happens | Demo effect |
|-----------|-------------|-------------|
| `rate × avg_duration > target_concurrency` | concurrency is binding — pool stabilizes at target, rate throttle is never reached | Reviewer drags rate up → no visible change, pool stays at target. Console shows "约束因子: 池子上限". |
| `rate × avg_duration < target_concurrency` | rate is binding — pool stabilizes at `rate × avg_duration`, never reaches target | Reviewer drags rate down → pool drains below target, stabilizes at a lower level. Console shows "约束因子: Call Rate 限速". |

This is an **explicitly educational design**: the demo actively shows Little's Law at
work. A reviewer who drags both sliders sees real mathematical relationships, not just
arbitrary numbers.

**Why two controls instead of one?** A single call-rate slider would produce concurrency
as a side effect, but the reviewer couldn't independently explore "what happens if I
allow more concurrency but limit the refill speed" (a scenario that mimics a bursty
call pattern where all active calls end simultaneously — rate throttle prevents a flash
flood). A single target-concurrency slider with no rate throttle means all concurrency
changes happen instantaneously — less interesting to watch.

**Pool model:**

```
tick_loop (every 500ms):
  pool_deficit = target_concurrency - active_calls
  new_calls = min(pool_deficit, rate_budget_remaining_this_tick)
  for i in range(new_calls):
    call_type = weighted_random(filter=enabled_types)
    duration_model = weighted_random([D1:30%, D2:50%, D3:15%, D4:5%])
    spawn_call(call_type, duration_model)
    active_calls += 1
  rate_budget_remaining_this_tick -= new_calls

call_ended(call_id):
  active_calls -= 1
```

Rate budget is reset every second (accumulated across ticks within the second).

**Architecture:**

```
console (P13)
  │
  │ REST API (start/stop/configure target concurrency + call type toggles)
  ▼
call_load_generator.py (P12)
  │
  ├─ mock S-CSCF UAC (from tools/chained_as_probe.py pattern)
  │    ├─ launches SIP INVITEs → AS
  │    ├─ tracks each call's lifecycle → end events back to generator
  │    └─ controls per-call duration (simulated core behavior: 2s / 10s / 25s / timeout)
  │
  └─ WebSocket event stream → console
       (per-call events: call_started, call_leg1_relayed, call_state_changed, call_ended,
        call_rejected_608, pool_status_update)
```

**Controls (console → generator REST API, two sliders + call type toggles):**
- `PUT /load/config` → `target_concurrency: int (1-50)`, `call_rate: float (0.1-10.0)`, `enabled_call_types: Set[str]`
- `POST /load/start` / `POST /load/stop`
- `GET /load/status` → current pool state, active_calls count, **which constraint is binding** ("池子上限" / "Call Rate 限速" / "池子已空")

Note the `/load/status` response includes the **binding constraint indicator** — console
displays this so the reviewer understands Little's Law interaction in real time.

**Scope boundaries.** The generator does **not** modify AS source code. It talks to AS
processes only via SIP (INVITE from mock S-CSCF) and observes via event streams. It can
be pointed at either AS or the chained topology (both Phase 1/2 demo modes).

### D7 — Call model definition

The load generator's call population. Mixed types, mixed durations, mixed outcomes.

**Call types (all Phase 1 + Phase 2 supported types):**

| # | Type | Origin | Result | Caller | Called |
|---|------|--------|--------|--------|--------|
| T1 | +86 E.164 | translation AS | convert to 0-prefix, relay | allow-listed | `+86...` |
| T2 | 0-prefix national | translation AS | keep format, relay | allow-listed | `0...` |
| T3 | 00-prefix international | translation AS | convert to `+...`, relay | allow-listed | `00...` |
| T4 | 4-digit short code | translation AS | no match → 404 | allow-listed | `1234` |
| T5 | reachable next hop | translation AS | 200 OK | allow-listed | any |
| T6 | unreachable next hop | translation AS | 3s timeout → fail | allow-listed | any |
| F1 | allow-listed caller | anti-fraud AS | relay | allow-listed | any |
| F2 | block-listed caller | anti-fraud AS | 608 Rejected | block-listed | any |
| F3 | high-rate caller | anti-fraud AS | 608 Rejected | high-rate | any |
| F4 | missing PAI | anti-fraud AS | fail-open → relay | any | any |

**Duration model (generator-controlled core behavior):**

| # | Weight | Behavior |
|---|--------|----------|
| D1 Fast | 30% | Core answers 200 OK in 1s, BYE after 2s |
| D2 Medium | 50% | Core answers 200 OK in 2s, BYE after 8-15s |
| D3 Long | 15% | Core answers 200 OK in 2s, BYE after 20-30s |
| D4 Timeout | 5% | Core never answers → AS 3s no-answer tear-down |

**Console controls over this model:**
- **Target concurrency slider (1-50)** → pool size (D-P3-6)
- **Call type toggles** → which of T1-T6, F1-F4 are in the selection pool
- Duration weights are **not user-adjustable** (P13 out of scope; defaults are stable and
  demo-ready)

### D8 — Phase 3 structure: two items, strict serial, v1.0.0 exit

**Decision.** Phase 3 has exactly two items, worked sequentially on a new long-lived
branch (`phase3` off `main`). Pipeline for both items keeps the full `AGENT.md` §5.1
ceremony with read-only review gates.

**Item boundaries (strict — no overlap):**

| | P12 Call Load (backend) | P13 Enhanced Console (frontend) |
|---|---|---|
| **What it touches** | `tools/call_load_generator.py`, `tools/chained_as_probe.py` (reuse), AS internal API / WebSocket event format enhancements | `src/console/main.py`, vendored Chart.js, AGENT.md §4.4, `tests/integration/test_console.py` |
| **Does NOT touch** | `src/console/main.py`, Chart.js, AGENT.md | AS source code, tools/, `as_platform` |
| **Exit criterion** | Load generator runs 10-20 concurrent mixed calls; console **old UI** shows them via existing Call Trace view | Console **new UI** with charts, gauge, dynamic topology; load generator controls integrated |
| **Version bump** | This repo → `0.10.0`; `as_platform` → no change | This repo → `1.0.0` |

**Chained demo compatibility.** P12 validates against both single-AS and chained-AS
topologies. P13's dynamic SVG topology visualization shows the call flow path
(S-SBC → anti-fraud → translation → core) when both AS processes are running.

> **P14 follow-on (2026-09-23).** v1.0.0 shipped before P9b landed. The interactive demo
> (`scripts/phase3-demo.sh full`) and console SVG still do not run the iFC-orchestrated chain
> on the wire. Alignment work — generator topology modes, multi-process `ims_mock` runtime,
> mode-aware console UI — is **`docs/phase3-p9b-alignment-plan.md`**.

**Exit barrier.** Phase 3 ends at `v1.0.0` when:
1. P12 acceptance items all verified with evidence (`docs/acceptance/report.md`)
2. P13 acceptance items all verified with evidence
3. Full demo run: console live, load generator running, reviewer can drag sliders and see
   call count change in real time
4. `make lint` clean, three test layers green
5. CHANGELOG consolidated, VERSION bumped to `1.0.0`
6. `phase3` branch merged into `main` with `--no-ff`

---

## 3. Work sequence

### P12 — Call Load capability

**Goal.** A load generator tool (`tools/call_load_generator.py`) that runs **N concurrent
SIP calls of mixed types and mixed durations** through either AS or the chained topology.
Each call's lifecycle progresses independently (建立 → 持续 → 拆线互不干扰). The AS
instances are stress-tested for concurrent isolation correctness.

**Why first.** P13 (Enhanced Console) needs real-time event data from P12's load generator
and AS instances. P12 can run acceptance on the **old console UI** (existing Call Trace
view) — no frontend work is required to validate the load generator.

**What P12 does NOT include.** Console charts, sliders, gauge, dynamic topology — that is
P13's job.

**Prerequisites.** None — P0 resolved, Phase 2 merged. Works on `phase3` branch.

#### Stage 1 — Requirements

New requirements IDs following the existing `REQ-F-*` pattern:

| ID | Requirement | Trace |
|----|------------|-------|
| REQ-F-038 | Load generator must maintain configurable concurrency pool (1-50) | D-P3-6 |
| REQ-F-039 | Load generator must support all Phase 1/2 call types (T1-T6, F1-F4) | D-P3-7 |
| REQ-F-040 | Load generator must simulate mixed call durations (D1-D4 weights) | D-P3-7 |
| REQ-F-041 | Load generator must be controllable via REST API (start/stop/config) | D-P3-6 |
| REQ-F-042 | AS instances must emit per-call events (call_started, call_state_changed, call_ended, call_rejected_608) via internal API / WebSocket | D-P3-6 |
| REQ-F-043 | Each concurrent call's lifecycle must complete independently (isolation guarantee) | D-P3-2 |
| REQ-F-044 | P8a timer cleanup must not cross-contaminate concurrent calls | D-P3-2 |

Update `docs/requirements/functional-and-nonfunctional.md` with these entries.

#### Stage 2 — Design

**Load generator architecture.** Leaky-bucket pool model (D-P3-6). Detailed flow:

```
tick_loop (every 500ms):
  while active_calls < target_concurrency:
    call_type = weighted_random(filter=enabled_types)
    duration_model = weighted_random([D1:30%, D2:50%, D3:15%, D4:5%])
    spawn_call(call_type, duration_model)
    active_calls += 1

spawn_call(type, duration):
  call_id = generate_unique_id()
  launch_mock_uac_invite(to=..., caller=..., dest=...)
  on_call_end_callbacks[call_id] = handle_end
  on_call_end(call_id, reason):
    active_calls -= 1
    emit_event("call_ended", {call_id, reason, duration})
```

**Event stream.** Generator and AS both emit events on a shared channel. Format:

```json
{
  "timestamp": 1726838400.123,
  "source": "load_generator" | "as_anti_fraud" | "as_translation",
  "event": "call_started" | "call_state_changed" | "call_ended" | "call_rejected_608" | "pool_status_update",
  "call_id": "...",
  "attributes": { ... call-type-specific fields ... }
}
```

Caller / called numbers, AS decision result, duration category — all in attributes.

**Pool status update** event (emitted by generator every tick regardless of pool change):
```json
{
  "event": "pool_status_update",
  "attributes": {
    "target_concurrency": 15,
    "active_calls": 12,
    "pending_starts": 0,
    "enabled_types": ["T1", "T2", "T5", "F1", "F2"]
  }
}
```

**Concurrency control edge cases to design for:**
- What if the tick loop fires while a call is ending (race between decrement and next increment)?
  → Generator uses asyncio.Lock around the pool check; Python GIL helps but explicit lock is safer.
- What if a call hangs indefinitely (neither ends nor times out from generator's perspective)?
  → Generator times out tracked calls at 2× the longest duration model (60s) and forcefully ends them.
- What if target_concurrency changes while calls are in flight?
  → Next tick applies the new target; no mid-flight call termination except the D4 timeout group.

Review gate: read-only review of the design document. Questions expected:
- "Is asyncio the right choice for the tick loop?" (Answer: generator is a standalone tool; it does not run inside sippy's ED2 loop)
- "Does this reuse the mock S-CSCF UAC from tools/chained_as_probe.py?" (Answer: yes, UAC pattern is copied from there)
- "How does the generator tell a call's duration type?" (Answer: generator controls the mock S-CSCF's response timing — the mock sleeps N seconds before sending BYE or before timing out)

#### Stage 3 — Implementation

Files to create:
- **`tools/call_load_generator.py`** — main load generator: pool management, mock UAC, event emission, REST API server. ~400-500 lines.
- **`tools/call_models.py`** (optional, if separation helps) — call type definitions, duration weight table, weighted-random selection. ~100 lines.

Files to modify (minimal, per D-P3-1 and D-P3-2 "no platform change, architecture unchanged"):
- **`src/as_app/call_controller.py`** (translation AS) — hook call event emissions at INVITE received, state transitions, BYE/CANCEL/timeout. These hook into the existing internal_api WebSocket (already used by P8/P9.5 for trace recording); no new platform method needed — the AS's internal_api handler is extended in-place.
- **`src/anti_fraud_as/call_controller.py`** (anti-fraud AS) — same event emission hooks, plus 608 reject event. Same mechanism as translation AS.
- **`src/console/main.py`** — extend WebSocket `/ws/events` handler to include new event types (no frontend changes yet, P12 exit uses old UI).
- **`config/`** — new config file or .env vars for generator defaults (target concurrency initial value, enabled types).

**Note on as_platform.** No changes to `../as_platform`. Event emission from CallController hooks into AS-local internal_api plumbing that already exists (extended in P10's platform extraction). The emission mechanism is a thin wrapper over the same event bus that CallController.tracer already uses for trace recording — no new protocol method, no new abstraction in the platform library.

Implementation steps (sequential):
1. Skeleton + pool tick loop + mock UAC launch (uses `tools/chained_as_probe.py` UAC pattern).
2. Call type table + weighted random selection + duration model → simulated core behavior (mock S-CSCF sleeps before BYE/timeout).
3. REST API (`/load/start`, `/load/stop`, `/load/config`, `/load/status`) — FastAPI, separate from AS internal_api.
4. Call event emission from both AS controllers — hooks into AS-local internal_api (extend existing handler, no platform change).
5. Generator WebSocket event stream → subscribe to AS events + its own pool events.
6. Concurrency isolation stress test: 20 concurrent calls, verify each CallController completes independently.
7. P8a timer cleanup test: concurrent calls with unreachable next hops → verify one call's timer cancellation does not affect another's armed timer.

#### Stage 4 — Tests

Three layers, all must pass (`AGENT.md` §11):

**Unit (`tests/unit/load_generator/` — new directory):**
- Pool tick loop: maintains target concurrency under various duration distributions.
- Weighted random selection: correct probabilities for call types and duration models.
- REST API: config change takes effect at next tick.
- Event format validation: every emitted event carries required fields.

**Integration (`tests/integration/`):**
- Single-AS load: 10 concurrent mixed calls through translation AS → every call completes its own lifecycle.
- Single-AS load with anti-fraud: 10 calls through anti-fraud AS → some 608 rejected, some relayed, all independent.
- Timer independence: concurrent calls with unreachable hops → verify P8a cancellation does not cross-contaminate (this is the test that P8a was created to enable; see phase2-plan.md P8a §3, P9.5).

**E2E (`tests/e2e/`):**
- Chained topology load: 10 concurrent calls → anti-fraud → translation → core. Console old Call Trace view shows all 20 legs (10×2) with correct state progression.
- Pool status WebSocket feed: console receives `pool_status_update` events every tick.

#### Stage 5 — Acceptance

New acceptance items: `docs/acceptance/criteria.md` adds `ACC-P12-001 … ACC-P12-00N`.

**Evidence per `AGENT.md` §4.8:**
1. **Reproducible probe run** — bash script that starts AS processes, starts generator at target_concurrency=15, waits 30 seconds, stops, shows per-call event trace keyed by Call-ID.
2. **Log excerpt** — one exemplary run showing call_1, call_7, and call_13 all progressing through different duration models and ending at different times, never cross-referencing each other's state.
3. **CI badge** — lint green, unit/integration/e2e layers green.
4. **Packet capture** — `captures/p12-load.pcap` showing ~15 concurrent call dialogs on SIP port 5060.

**Acceptance review gate.** Read-only reviewer checks:
- Does the evidence prove concurrent-call isolation, or just that the generator emitted events?
- Does P8a's timer population really behave correctly under concurrent load, or is it just "no crash"?
- Is the call model comprehensive enough (all 10 types, all 4 duration models)?

**Exit criteria for P12:**
- ✅ All REQ-F-038…044 satisfied with tests proving each
- ✅ Load generator tool runs from command line, no code changes required
- ✅ Both AS processes support concurrent isolation (tests prove, not just assume)
- ✅ `make lint` clean, three test layers green
- ✅ Old console Call Trace view shows all concurrent calls (console does **not** need Chart.js yet)
- ✅ `CHANGELOG.md` P12 entry, VERSION → `0.10.0`

### P13 — Enhanced Console

**Goal.** Replace the hand-run demo script with a **real-time operations dashboard** that
shows Call Load in action — live call count charts, state distribution pie charts, capacity
gauge, dynamic call-flow topology, and interactive controls (sliders + toggles) that the
reviewer can operate. **Perfectly replaces the manual demo.**

**Why second.** Depends entirely on P12's load generator (REST API + WebSocket event
stream) and P12's per-call event format. Without P12, P13 has nothing to show.

**Scope boundary.** P13 does **not** modify any AS source code or `as_platform`. It only
consumes what P12 already emits. It also does **not** implement call rate throttling or
complex filtering — sliders and toggles are the full control surface.

**Prerequisites.** P12 acceptance items all verified on `phase3`. Continues on the same
branch; P12 is merged into the branch before P13 starts (no parallel work).

#### Stage 1 — Requirements

New requirements IDs:

| ID | Requirement | Trace |
|----|------------|-------|
| REQ-F-045 | Console must show live call count over time (rolling window line chart) | D-P3-5 |
| REQ-F-046 | Console must show state distribution (pie chart: active, rejected_608, completed, timeout) | D-P3-5 |
| REQ-F-047 | Console must show capacity gauge (active_calls / target_concurrency) | D-P3-5, D-P3-6 |
| REQ-F-048 | Console must show dynamic topology visualization (SBC → anti-fraud → translation → core, call-flow arrows with state coloring) | §4.4 AGENT.md dynamic topology |
| REQ-F-049 | Console must expose load generator controls (target concurrency slider, call type toggles, start/stop buttons) | D-P3-6 |
| REQ-F-050 | Console must accept vendored Chart.js (~80KB UMD bundled) under `/static/` | D-P3-4 |

#### Stage 2 — Design

**Console architecture change.** Before (Phase 2): single `CONSOLE_PAGE` inline HTML,
no external references, all assets in one Python string. After (Phase 3 P13):

```
console server (FastAPI)
  │
  ├─ GET /            → CONSOLE_PAGE (inline HTML, <script src="/static/chart.umd.min.js">)
  │                      │
  │                      └─ JavaScript frontend:
  │                         ├─ WebSocket → /ws/events → AS call events
  │                         ├─ WebSocket → /ws/load → load generator events
  │                         ├─ REST → PUT /load/config, POST /load/start|stop → generator control
  │                         ├─ Chart.js instance 1: call count rolling line chart (30s window)
  │                         ├─ Chart.js instance 2: state distribution pie chart (updated on every event)
  │                         ├─ Chart.js instance 3: capacity gauge (target vs active)
  │                         ├─ SVG topology: SBC → anti-fraud → translation → core
  │                         │    └─ arrow color changes: active→green, 608→red, timeout→orange
  │                         │    └─ arrow thickness: proportional to active call count on that hop
  │                         ├─ Call type toggles (checkboxes for T1-T6, F1-F4)
  │                         └─ Target concurrency slider (1-50, live value display)
  │
  ├─ /static/ → mounted directory serving Chart.js UMD bundle
  └─ /ws/events, /ws/load, /load/* → existing AS endpoints (extended in P12)
```

**Multi-panel layout (CSS Grid):**
```
┌──────────────────────────────────────────────────────┐
│ Status Bar (version, uptime, active_calls, target)   │
├──────────────┬───────────────────┬───────────────────┤
│ Left Nav     │ Center Panel       │ Right Panel        │
│              │                    │                    │
│ • Call Trace │ Call Count Line    │ State Pie          │
│ • Rules      │ Chart (Chart.js)   │ Chart (Chart.js)   │
│ • Screening  │                    │                    │
│ • Control    │ Capacity Gauge     │ Dynamic Topology   │
│              │ (Chart.js)         │ (SVG)              │
│              │                    │                    │
│              │ Load Controls                     │
│              │ ┌──────────────────┐                 │
│              │ │ Target: [slider] │                 │
│              │ │ [T1][T2]...[F4]  │                 │
│              │ │ [Start] [Stop]   │                 │
│              │ └──────────────────┘                 │
├──────────────┴───────────────────┴───────────────────┤
│ Bottom: Live Call Trace (filterable, Call-ID / type)  │
└──────────────────────────────────────────────────────┘
```

**Demo flow (the perfect replacement for the manual demo):**
1. Reviewer opens console. Sees status bar green (AS up). Sees Chart.js charts (all zero,
   no active calls yet).
2. Reviewer drags target concurrency slider to 15.
3. Reviewer clicks Start.
4. Within ~1 second: call count line chart begins rising, state pie begins forming,
   topology arrows thicken and colour.
5. Reviewer drags slider to 5 → chart drops, pool adjusts, topology thins.
6. Reviewer unchecks T3 → no new international calls appear. Re-checks → they resume.
7. Reviewer clicks Stop → pool drains, charts return to zero.

**AGENT.md §4.4 amendment** — a short ADR-level record that explains the vendoring
decision, lists vendored libraries, and updates the integration test accordingly.

#### Stage 3 — Implementation

Files to create:
- **`src/console/static/chart.umd.min.js`** — Chart.js 4.x UMD bundle, vendored (~80KB).
- **`src/console/static/chart.umd.min.js.LICENSE.txt`** — Chart.js Apache-2.0 license copy
  (vendored libraries must carry their licence notice, `AGENT.md` §4.7).

Files to modify:
- **`src/console/main.py`** — rewrite `CONSOLE_PAGE` constant: add Chart.js `<script>`
  tag, restructure layout into multi-panel grid, add control panel with slider and
  toggles, add three Chart.js instances and one dynamic SVG topology instance. FastAPI
  app must mount `/static/` directory. WebSocket event handlers must process new event
  types and update Chart.js data arrays.
- **`AGENT.md` §4.4** — add vendored-libs clause + inventory table (D-P3-4).
- **`tests/integration/test_console.py`** — update hardcoded "no external `<script>`"
  check to "all external `<script src>` resolve to `/static/`".
- **`docs/architecture/adr/`** — new ADR `ADR-0011` "Vendored third-party frontend
  libraries permitted" (governance change needs ADR per `AGENT.md` §4.5).

**Implementation steps (sequential):**
1. Download Chart.js UMD bundle (4.x) from official CDN → `src/console/static/chart.umd.min.js`.
   Verify it works offline (Open local HTML file that references it → no 404, charts render).
2. Mount `/static/` in FastAPI console server. Test that `GET /static/chart.umd.min.js`
   serves the file when running `make console`.
3. ADR-0011 draft + AGENT.md §4.4 amendment → commit to branch (governance change first).
4. Integration test update: `test_console.py` now checks script sources resolve to `/static/`.
5. Console layout restructure: CSS Grid replaces current left-nav + single-centre-panel.
   Preserve existing functionality (Call Trace, Rules, Screening) while adding Control panel.
6. Chart.js instances: call count line chart (rolling 30s window, update on every
   `pool_status_update` event), state distribution pie (update on every
   `call_state_changed` event), capacity gauge (`active_calls / target_concurrency`).
7. Dynamic SVG topology: arrows from SBC → anti-fraud → translation → core. Arrow
   thickness = active_calls on that hop; colour = green (all), red (608 on that hop),
   orange (timeouts on that hop).
8. Control panel wiring: slider → REST `PUT /load/config`, toggles → same config endpoint,
   Start/Stop → `POST /load/start`/`POST /load/stop`. All asynchronously update from
   `pool_status_update` events so slider value never drifts from actual generator state.

#### Stage 4 — Tests

**Unit:** Chart.js data array management (push/pop rolling window), event → chart update
routing, control panel config serialization.

**Integration:**
- Console page loads with no external network access (offline test: run console in
  Docker with no internet; charts still render).
- No `<script src>` outside `/static/` (updated test from Stage 3).
- WebSocket event processing: `pool_status_update` event updates line chart;
  `call_state_changed` updates pie chart.
- Control panel: slider → REST API call → generator responds → pool_status_update event
  reflects change → console gauge updates → visual feedback loop closed.

**E2E:** Full console session test: (1) open console, (2) start load generator at 15,
(3) wait 10s, (4) verify call count chart shows values, (5) slide to 5, (6) verify chart
drops, (7) stop → charts clear → no console crash.

#### Stage 5 — Acceptance

New acceptance items `ACC-P13-001 … ACC-P13-00N`.

**Evidence per `AGENT.md` §4.8:**
1. **Reproducible demo run** — one full demo script walkthrough (from reviewer's
   perspective) that uses the new console as the single interface.
2. **CI badge** — lint green, three layers green.
3. **Offline demo** — console run in Docker with `--network=none` (no internet) → charts
   still render, all controls work.
4. **Packet capture** — SIP traffic during demo + console HTTP/WebSocket traffic.

**Acceptance review gate.** Read-only reviewer checks:
- Does the console actually work **without** an internet connection? (vendored Chart.js
  is the hard case here — Chart.js 4.x UMD bundle must render charts standalone)
- Can the reviewer complete the full demo without touching a command line? (The slider
  → REST → generator → event → chart feedback loop must close)
- Is the topology visualization useful, or just decoration? (The arrow colour/thickness
  should let the reviewer see which AS hop the 608 rejections are concentrated on)

**Exit criteria for P13:**
- ✅ All REQ-F-045…050 satisfied
- ✅ Chart.js vendored, `/static/` mount works, offline demo green
- ✅ Control panel → load generator REST API → WebSocket event stream → chart update:
  the full loop is verified E2E
- ✅ Demo script rewritten to use only the new console (no command-line operations
  except starting AS processes and load generator)
- ✅ AGENT.md §4.4 amended + ADR-0011 committed
- ✅ `make lint` clean, three layers green
- ✅ `CHANGELOG.md` P13 entry, VERSION → **`1.0.0`**
- ✅ **Phase 3 complete** — `phase3` branch ready for merge

---

## 4. Repository and branch strategy

| Item | Branch | Repository |
|------|--------|------------|
| **Phase 3 (P12 + P13)** | **`phase3`** — long-lived, created once from `main` | this one |
| P12 Call Load backend | `phase3` — worked directly on the integration branch | this one |
| P13 Enhanced Console | `phase3` — worked directly on the integration branch | this one |
| ADR-0011 + AGENT.md §4.4 amendment | `phase3` — part of P13 | this one |

Same pattern as `phase2-plan.md` §4 — one long-lived branch, no per-item branches
unless parallel work is needed (not expected; P12/P13 are sequential).

Per `AGENT.md` §13: no branches without purpose and end condition. `phase3`'s purpose
is to carry P12 + P13 to completion before merging into `main`. Its end condition is
Phase 3 acceptance verified + `v1.0.0` tag created.

`phase3` branch deleted after merge (same as Phase 2 pattern — long-lived integration
branch, deleted when done).

---

## 5. Pipeline

Both P12 and P13 follow the `AGENT.md` §5.1 pipeline with full ceremony and read-only
review gates between stages:

```
Stage 1: Requirements    → review gate: completeness, traceability, gap coverage
Stage 2: Design         → review gate: correctness, edge cases, file scope
Stage 3: Implementation → review gate: code quality, no scope creep, tests written alongside
Stage 4: Tests          → review gate: all three layers green, tests actually prove things
Stage 5: Acceptance     → review gate: evidence complete (AGENT.md §4.8), every ACC item has proof
```

This is the same pipeline Phase 2 used. No ceremony lightening for Phase 3. Phase 3 is
**two** items, each going through all five stages, with review gates after each stage.

---

## 6. Risks and unknowns

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| AS concurrent isolation breaks under load (P8a timer cross-contamination resurfaces) | Medium | High — P12's core promise fails | Stage 4 integration tests explicitly exercise concurrent unreachable-hop scenarios; Phase 2 P8a fixed the known defect; P12 adds new tests to catch anything new |
| Load generator's mock UAC pattern doesn't match real S-CSCF behavior well enough for demo quality | Medium | Medium — demo is functional but doesn't look real | Run one P12 probe with a real SBC (if available), but fallback to mock UAC for CI; demo quality is measured by the reviewer's experience, not fidelity |
| Chart.js 4.x UMD bundle doesn't work offline (needs internet for fonts, icons, etc.) | Low | Medium — offline demo breaks | Stage 3 step 1 explicitly verifies offline rendering; if broken, switch to ESM version with `importmap` pointing to `/static/` paths, or use version 3.x which was tested more for offline use |
| Console control panel slider doesn't actually change pool size (feedback loop breaks) | Low | High — demo becomes a recording, not interactive | Stage 4 E2E test covers full loop: slider → REST → generator → WebSocket event → chart update → slider value display. Must be testable. |
| Single process `ED2` loop gap grows visibly at 15+ concurrent calls | Low | Low — reviewer sees slightly delayed SIP but demo still "works" | This is the P9.5 measured constraint; each AS runs as its own process (separate ED2), so per-AS gap is at worst ~0.05s at 15 calls — imperceptible in demo |

---

## 7. Open items — to resolve before P12 starts

| Item | What to decide | By when |
|------|---------------|---------|
| Caller/called number population for generator | Phase 1 demo has a fixed fleet of numbers. Does the generator need a configurable call-number generator (e.g., incrementing + random), or reuses the fixed fleet? | P12 Stage 2 (design) |
| Load generator logging level | Should generator emit every call detail to stdout for demo narration, or aggregate by state? | P12 Stage 3 (implementation) |
| Load generator → AS topology | P12 must support: generator → single-AS (both translation and anti-fraud, one at a time); generator → S-CSCF → chained AS → core (full topology). Which is the default for acceptance? | P12 Stage 1 (requirements) |

---

## 8. Phase 3 in the gap register — and what's deferred

Phase 3 closes **zero registered gaps** from `docs/production-gaps.md`. It is a
**display-capability phase**, not a gap-closing phase. The revision-1 direction (D3
Session Registry + Admission Control, B3 DNS SRV) would have closed 4 of 6 rows from the
gap table; all four are deferred to Phase 4+.

| Gap | Closed by Phase 3? | Deferred to |
|-----|--------------------|-------------|
| Chain shared call context (ICID) | ✗ | D3 (Phase 4+) |
| Restart safety / session recovery | ✗ | D3 + D2 |
| Admission control / back-pressure | ✗ | D3 |
| Peer addresses (no DNS/SRV) | ✗ | B3 |
| HA / active-standby | ✗ | D2 (Phase 5+) |
| Rules drift between environments | ✗ | B2 |

This deferral is an explicit decision aligned with `phase2-plan.md` D1 ("portfolio
piece, not a product"). The maintainer may revisit it after Phase 3's portfolio
display is validated.

---

## 9. What Phase 3 enables

Phase 3 does not build the platform's production capability — it builds the platform's
**demo capability**. But it creates natural entry points for later phases:

- **Phase 4 D3 (Session Registry + Admission Control)** — P12's event stream format
  already carries per-call state transitions; adding a registry to the generator's
  pool model is a natural next step, not a rewrite. The Session Registry becomes
  the control layer that the load generator already demonstrates a need for.
- **Phase 4 D1 (STIR/SHAKEN)** — P12's call model has F4 "missing PAI identity" as a
  deliberate gap case; STIR/SHAKEN would populate that gap with an attestation. The
  load generator's mixed population model can include STIR-attested callers.
- **Phase 4 B1 (API Exposure)** — P12 already exposes `/load/*` REST API; P13 already
  exposes `GET /sessions/{call_id}` implicitly. Formalizing an OpenAPI contract is a
  surface-polish step on existing endpoints.
- **Phase 4+ B3 (DNS SRV)** — remains a quick gap close. The console's dynamic topology
  would gain a "resolved addresses per hop" display that visualises SRV in action.
