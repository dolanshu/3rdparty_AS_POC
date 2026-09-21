# Post-Phase-2 Directions — what comes after P11 and why

- **Status:** decision made (revision 2) — Call Load + Enhanced Console
- **Date:** 2026-09-21
- **Owner:** project maintainer
- **Context:** Phase 2 (P8–P11) is complete and merged into `main`. `as_platform` library
  has been published as a public GitHub repository. This repository is `v0.9.0`; the
  library is `v0.2.0`. CI is green.

---

## Part A — research record (preserved unchanged from revision 1)

### 1. How this document came to be

Phase 2's closing conversation asked two questions the repository had not yet answered in writing:

1. What is the CDR situation for a **third-party** AS (outside the operator IMS)? Does the AS need to generate one?
2. Beyond the session / context / load direction the maintainer proposed, what other directions exist after Phase 2?

The first question was answered by searching 3GPP TS 32.260 (IMS charging) and related material. The second was answered by surveying the feature lists of commercial and open-source SIP AS platforms (Kamailio, Sipwise NGCP, dSIPRouter, PortSIP UCaaS, 中兴 vIMS, Ericsson Cloud IMS, Nokia VoLTE core) and comparing them against this repository's registered production gaps.

This document records every serious candidate direction with its rationale so that a later conversation does not have to re-derive them.

### 2. Key finding — CDR is not a first-class direction for a third-party AS

The maintainer's intuition was correct: IMS charging trust is inside the core network. 3GPP TS 32.260 names **S-CSCF, P-CSCF, I-CSCF, BGCF, IBCF, and MGCF** as the standard CDR generators via Diameter Rf/Ro interfaces to the CCF (Charging Collection Function). The **home AS** (inside the operator IMS) can participate in online charging via Ro, but the **third-party AS** sits outside the S-SBC trust boundary. Operators do not use external AS records for billing.

What the third-party AS *does* generate that matters to someone is:

- **Usage records for its own operator** — "N calls today, M rejected by anti-fraud, K minutes of relay" — a reconciliation surface between the AS provider and the S-SBC operator, not a billing surface.
- These are a **natural byproduct** of a call session closing cleanly, not an independent direction.

Conclusion: CDR (as a standard charging direction) is **removed from the candidate list**. Usage records are folded into the Session Registry direction below.

### 3. The prerequisite — do this first

Nothing on the list below is credible until this is done.

#### P0 — Publish `as_platform` library to a reachable remote (private is fine)

**Status: resolved 2026-09-21.** The library is now a public GitHub repository at
`https://github.com/dolanshu/as_platform`. CI on this repository successfully clones it
and runs `make check` against a real checkout. The "two repositories" claim of P10/P11 is
no longer hollow.

### 4. Depth directions — pick one to do completely

Each direction in this section is large enough to be a Phase 3 item on its own. They each have a beginning, middle, and end — a reviewer who sees the completed item can say "this project is genuinely capable in this dimension."

#### Depth-1 — STIR/SHAKEN (RFC 8224/8225) — identity verification on the originate side

**The story.** RFC 8688 (608 Rejected) says "an automated engine rejected this call." STIR/SHAKEN (RFC 8224/8225) says "the caller identity on this call was verified by an authoritative entity." They are complementary, not alternative. A reviewer who sees 608 without STIR will ask "but how do you know the suspect caller number is real?" A reviewer who sees both gets a complete anti-abuse story: the AS verifies the caller's identity before applying its reputation engine.

**Why now.** D5 explicitly deferred STIR/SHAKEN ("out of scope" — ADR-0007). The anti-fraud AS is its natural home — this is not platform-level, it is use-case-level. Regulators are mandating STIR/SHAKEN worldwide (FCC STIR/SHAKEN mandate in the US, Ofcom in the UK, CRTC in Canada). The `as_platform` library needs no changes; this is purely `src/anti_fraud_as/` work.

**Connection to existing work.** P11 already produces self-signed certificates for TLS termination; the same generation script pattern can produce STIR signing keys (Ed25519 JWK/JWS). P8's probe pattern (probe first, design after) applies: probe sippy's handling of the `Identity` header before committing to implementation.

**Engineering scope.** Medium. STIR signing is pure Python cryptography (Ed25519 + JOSE/JWS); the AS adds an `Identity` header to every outbound INVITE from the signing module, and verifies incoming `Identity` headers from trusted signers. sippy does not need core modification — it passes unknown headers through verbatim (verified in ADR-0007).

#### Depth-2 — HA Active-Standby with state replication

**The story.** "This AS can survive a process crash and keep serving live calls." Sipwise NGCP (Kamailio-based) emphasizes two-node active-standby with state replication; Kamailio's `syncer` module and `dispatcher` module are the canonical mechanisms; 中兴 vIMS lists "5-level disaster recovery, 99.999% reliability" as a headline feature.

**What Phase 2 already laid.** P11 gave us `RedisStateStore` for durability-after-restart. Session state that lives in Redis survives a restart. What is missing is: active-standby election (who is the primary), real-time state replication for in-flight calls (Redis Pub/Sub), and SIP OPTIONS keepalive so S-SBC knows to fail over.

**Engineering scope.** Large. State replication for *in-flight calls* (not just durability) is hard — it means every call state change has to be propagated to the standby, and the standby has to be able to take over at any point without dropping transactions. But the **display value is enormous**: a demo that kills the primary mid-call and the call continues on the standby is more convincing than any feature list.

#### Depth-3 — Session Registry + Call State Machine + Admission Control (maintainer's direction)

**The story.** This was the maintainer's own proposal before this document was written. Every call should be trackable in a **unified registry** that answers: how many calls are active right now, what state is each one in, which leg of which AS chain is it on, how long has it been there. And when active calls exceed a threshold, new calls get `603 Decline` with `Retry-After` instead of queuing indefinitely.

**Connection to existing work.** The gap is known: P9.5 found "no admission control — the 3-second wall-clock timeout is the only thing that turns a slow call into a failed one." P9 found "no cross-AS session key" — the fix is to use `P-Charging-Vector`'s ICID, which P9 measured is preserved end-to-end but nothing is keyed on it yet. P11's `RedisStateStore` is the natural registry backend (process-level for now, cross-process when needed). Session close naturally produces usage records for the AS's own operator (see CDR finding, §2).

**What this means for the platform.** `BaseCallController` moves from "create a controller, handle INVITE, dispose when done" to "register the call in a lifecycle-aware registry, drive it through explicit state transitions (`INIT → RECEIVED → DECIDING → ... → CLOSED`), and emit close events." This is a **platform library** change, not a use-case change — it improves every AS that uses `as_platform`.

**Engineering scope.** Medium. The state machine itself is conceptually simple; the work is in identifying the registry's lifecycle boundaries (what exactly gets created, what exactly gets torn down, and who tears it down — the controller? the stack? a watchdog timer?), and in the admission policy hook that the platform exposes and each AS overrides.

### 5. Breadth directions — pick one to lay wide

These directions do not deepen an existing narrative. Instead, they demonstrate that the `as_platform` abstraction is *not* just a refactoring of the two use cases that happened to exist. They add genuinely new dimensions the platform supports.

#### Breadth-1 — Service Capability Exposure API (programmable platform)

**The story.** Every major IMS vendor (Nokia, ZTE, Ericsson) now emphasizes "open APIs" and "capability exposure" as the differentiator of a modern AS platform — not just SIP processing, but a programmable telecom service platform. A third party that cannot see or consume what the AS decided cannot integrate with it.

**Current state.** This repo has `GET /counters` and a rules edit API. `as_platform` exposes `internal_api` as a shell that each use case extends. But there is **no OpenAPI contract**, no versioning, no authentication on the API, and no callback/webhook mechanism for pushing verdicts out.

**What this would mean.** Add a new REST surface with a proper contract: `POST /api/v1/translate` (number translation test), `POST /api/v1/screen` (fraud verdict test), `GET /api/v1/sessions/{icid}` (session status by ICID — the cross-AS key from D3), `POST /api/v1/webhooks` (callback registration). Publish an OpenAPI spec. Add API key authentication.

**Engineering scope.** Medium. Extends `as_platform`'s `internal_api` shell with new contracts and security. The platform gains a genuinely new surface that neither Phase 2 use case explicitly designed for.

#### Breadth-2 — Multi-tenancy

**The story.** One AS instance, multiple independent operators sharing it. Each tenant gets its own rules, its own anti-fraud blacklist, its own counters, and is completely isolated from the others. PortSIP UCaaS calls this "multi-tenant architecture for cloud deployment" and highlights it as "essential for cloud-native operations."

**Connection to existing work.** Nothing in the current codebase has a tenant concept. Session registry (D3) gets a tenant-ID dimension; `RedisStateStore` gets a per-tenant namespace; rules files and screening data get per-tenant directories; observability (counters, traces) get a tenant key.

**Engineering scope.** Medium-large. Multi-tenancy touches every subsystem — routing rules, screening data, state store, counters, internal API, and the console. It is the biggest breadth direction.

#### Breadth-3 — RFC 3263 DNS SRV/NAPTR peer resolution

**The story.** The smallest direction in the list. Currently every peer address is a hard-coded `127.0.0.1:<port>`. Real SIP entities discover peer addresses via DNS SRV (e.g. `_sip._udp.as.example.com` resolves to `as1.example.com:5060` with priority/weight). This is already a registered production gap under Routing catalogue coupling and no operator would deploy an AS that cannot resolve its peers via DNS.

**Connection to existing work.** `NextHop.address` → `NextHop.resolved_addresses` (a list of `(host, port, priority, weight)` derived from SRV lookup), plus a 30-60 second cache to avoid hammering the resolver. dnspython is a standard dependency.

**Engineering scope.** Small. Quick win. A reviewer with telecom background will notice this was missing in Phase 2.

#### Breadth-4 — A third AS use case (if it introduces genuinely new dimensions)

**The story.** The most direct way to prove P10's abstraction is not tailored to the two use cases that existed when it was written: build a third use case without modifying `as_platform`. **BUT** — D2 from Phase 2 plan is explicit: the selection criterion is **orthogonality**, not novelty. A third use case that covers the same dimensions (stateless · stateful · rewrite · reject) is isomorphic and proves nothing.

**What genuinely new dimensions would qualify?** A pre-pay AS (online balance check + Diameter Ro) introduces real-time external decision making and an online charging interaction. A multi-leg call forwarding AS (Call Forwarding Unconditional / Busy / No Answer) introduces per-destination routing logic and supplementary service handling. An emergency call routing AS introduces location-aware routing (PSAP) and regulatory logging requirements.

**Engineering scope.** Medium-large, and only worth it if the selected use case introduces genuinely new dimensions the existing two do not.

### 6. The ceremony cost — one or two items, not four or five

Every item in Phase 2 ran through the §5.1 pipeline (requirements → design → implementation → tests → acceptance), with an independent read-only review gate after each stage. This ceremony produces high-quality artefacts but it is **not cheap** — P10 alone had seven implementation steps, each with its own gate and findings.

The recommendation for Phase 3 is **one depth direction and optionally one breadth direction**, not more. Two complete items produce a coherent phase story; three shallow ones produce three half-finished ones.

### 7. What the plan says and why this document says more

`docs/phase2-plan.md` D10 explicitly selected TLS and the capacity harness as the two Phase 2 enhancement items. CDR was rejected in D10 with the note "it should be reconsidered at P10/P11, where 'what does every AS get for free' is exactly the question the platform must answer." This document is that reconsideration.

The D10 CDR note held under the assumption that CDR would be the platform's cross-cutting answer. The 3GPP finding in §2 changes that assumption — CDR is not the right cross-cutting answer for a third-party AS. But the *spirit* of D10 ("what does every AS get for free") still applies: session registry (D3), capability exposure (B1), and STIR/SHAKEN (D1) are all candidate cross-cutting answers that align with the third-party AS positioning.

Phase 2 plan D3 (the gap register is repositioned, not abandoned) also holds. The gaps registered in Phase 2 that the directions above close are:

| Registered gap | Closed by |
|----------------|-----------|
| Chain carries no shared call context beyond pass-through headers | D3 (Session Registry with ICID key) |
| Single process, no persistence → Restart safety, session recovery, watchdog | D2 (Active-Standby), D3 (Registry + dispose on close) |
| No admission control or back-pressure; fixed 3-second timeout is the only wall-clock boundary | D3 (Admission Control) |
| Peer addresses are 127.0.0.1 ports; no DNS/SRV resolution | B3 (DNS SRV/NAPTR) |
| No HA, no cluster, no active-standby | D2 |
| Rules drift between environments (two YAML files, differing only in addresses) | B2 (per-tenant isolation) |

### 8. Decision space — choose before this document ages

This document records the space of credible options. The maintainer must decide before merging `phase2` into `main`:

1. **P0 (library remote) — is this done or explicitly deferred?** It is a prerequisite for everything else.
2. **Depth direction — which one, and why?** D1 = identity + anti-abuse completeness; D2 = HA + telecom-grade reliability; D3 = session state + admission control. All three are defensible and each tells a different portfolio story.
3. **Breadth direction — optional, which one, and why?** B1 = platform programmability; B2 = multi-tenant deployment model; B3 = quick gap close; B4 = abstraction validation.
4. **Pipeline — keep the full §5.1 ceremony for Phase 3 items, or lighten it?**

Nothing in this document commits the repository to any direction — it only records the credible options, their trade-offs, and their connection to the existing work so a fresh conversation does not have to re-derive them.

---

## Part B — Phase 3 decision record (revision 2, 2026-09-21)

### 9. Decision — Call Load capability + Enhanced Console

#### 9.1 What was selected — and why this document has two revisions

Revision 1 of this document (the original Part B) selected **D3 (Session Registry + Admission Control)** as the depth direction and **B3 (DNS SRV/NAPTR)** as the breadth direction. That selection was reversed after a round of detailed questioning with the maintainer.

The reversal is not a rejection of D3 or B3 on their own merit — it is a recognition that **the portfolio purpose of the repository (`phase2-plan.md` D1: "display value outranks functional completeness") is better served by a different Phase 3 focus.** D3 and B3 remain valid future directions — they are pushed to Phase 4 and beyond.

Phase 3 selected direction — two items, one phase, strict serial:

| Item | What it does | Why it wins over D3/B3 |
|------|-------------|----------------------|
| **P12 Call Load** | Demonstrate the AS handles **N concurrent SIP calls of mixed types, mixed durations, and independent lifecycle** — not just single-call functional correctness | Every reviewer of Phase 1/2 saw one call at a time. Call Load shows the AS processes "a crowd of calls" — a capability that the architecture already supports (CallController per-call instances share nothing but an ED2 loop) but was never demonstrated. The gap closed here is not in the gap register — it is in the **reviewer's mental model**: "Phase 1/2 validated single-call correctness; Phase 3 validates multi-call concurrency." |
| **P13 Enhanced Console** | Rebuild the console as a **real-time operations dashboard with live charts, dynamic topology, and interactive controls** (sliders, toggles) — replacing the hand-run demo script that reviewers walk through | P12's Call Load needs a way to **show** the concurrent calls. The enhanced console is not "UI polish" — it is the delivery vehicle for P12's display value. Every reviewer who sees the console with Chart.js live charts, a capacity gauge, and a slider that they can drag to change call count will grasp "this system is managing real load, not running a scripted demo." |

Both items were validated through a round of structured questioning (recorded in the conversation history). The key finding from that round:

1. **AS architecture does not need to change** — CallController per-instance isolation already works. The Call Load direction is about **demonstrating** what exists, not **inventing** what doesn't.
2. **"No benchmark numbers" (D10) is not a problem** — real-time display numbers ("当前活跃 call 数 = 12") are live demo artefacts, not published claims. D10's prohibition targets README/CHANGELOG headline numbers, not console displays.
3. **AGENT.md §4.4 ("no third-party front-end libraries") must be amended** — vendoring Chart.js resolves this while keeping offline demo capability.

#### 9.2 Rejected — D3, B3, and the revision-1 selection

| Direction | Why pushed to later | Natural successor phase |
|-----------|---------------------|------------------------|
| D3 Session Registry + Admission Control | Platform-level change (改 `as_platform.BaseCallController`)，对 portfolio 展示的直接价值弱——reviewer 很难"看见" admission control 在工作，除非专门设计阈值溢出场景。Call Load 的 display value 更直接。 | Phase 4+，在 Call Load 展示了并发能力之后。此时 Session Registry 作为 Call Load 的状态观测基础设施，比作为 admission control 的钩子更容易 justify。 |
| B3 DNS SRV/NAPTR | Small scope 但 display value 很低——reviewer 看到 `127.0.0.1:5060` 和 `_sip._udp.sbc.example.com` 看不出区别。不解决当前最紧迫的展示问题。 | Phase 4+，作为 P12/P13 之后的 quick gap close。 |
| D1 STIR/SHAKEN | use-case 级改动，只改 anti-fraud AS。同 revision-1 的 rejection 理由不变。 | Phase 4+，当 anti-fraud 故事需要完整性时。 |
| D2 HA Active-Standby | Engineering scope Large，且依赖 D3 的 Session Registry 作为前置。 | Phase 5+。 |

### 10. Phase 3 strategic decisions

#### D1 — Phase 3 purpose: demonstrate multi-call concurrency capability

**Decision.** Phase 3 demonstrates what the AS architecture already supports but Phase 1/2 never showcased: multiple SIP calls of different types and durations running **in parallel, independently, on the same AS process**. The display value of "N calls of mixed types all progressing through their own lifecycles simultaneously" outranks platform-layer abstractions (D3) or routing refinements (B3).

**Consequence.** No changes to `as_platform` library are required for P12/P13. The direction changes are entirely within this repository.

#### D2 — Do not change AS architecture; CallController per-call isolation already works

**Decision.** Each AS instance already handles per-call isolation through sippy's INVITE handler — each incoming INVITE creates one `CallController` with its own `self.call_id`, `self._incoming`, `self._outgoing`. The controllers share nothing but the process-wide `ED2` event loop. Call Load will **validate** this isolation under concurrent load, not **modify** it.

**Rationale.** P9.5 measured that the `ED2` loop gap grows from 0.03s to 0.12s at 64 concurrent calls when all instances run in one interpreter. But Phase 3 runs each AS as its own process (各自独立的 ED2 loop) — the bottleneck is per-AS, not cross-AS.

**Consequence.** The engineering risk for P12 is low — the concurrency is already there, it just hasn't been exercised. The unknowns are at the edges (P8a's timer population under concurrent load, whether one call's timer can cancel another's), not in the core model.

#### D3 — Supersede D10's "no benchmark numbers" — clarify boundary

**Decision.** Phase 2 plan D10's prohibition ("no calls-per-second and no latency figure") applies to **published documentation** (README, CHANGELOG, demo script), not to **live demo displays**. The console may show real-time call counts, rate, and duration distributions as interactive demo artefacts. No headline numbers will be committed to documentation.

**Boundary.** "当前活跃 call 数 = 12" (console real-time display) — permitted. "本 AS 支持 50 QPS" (README) — still prohibited.

**Consequence.** Capacity numbers that the load generator produces are demo-only. The demo script will frame them as "here's how many calls we chose to run" rather than "here's what the system can handle."

#### D4 — Amend AGENT.md §4.4: vendored third-party frontend libraries permitted

**Decision.** AGENT.md §4.4 is amended to replace "No third-party front-end libraries; plain HTML/CSS/JS only, so the demo works offline" with "Third-party front-end libraries are permitted when vendored into the repository (`src/console/static/`). No CDN-only references — every vendored file must work offline without external network access."

**Rationale.** Portfolio demo quality is the overriding concern. Chart.js (~80KB, vendored) provides real-time line charts, pie charts, and gauges in one-third the code volume of hand-written Canvas 2D. Vendoring keeps the offline-demo guarantee intact.

**Affected code.** `tests/integration/test_console.py` has hardcoded checks for no external `<script src>` / `<link href>`. These must be updated to verify that all external references point to `/static/` paths within the console process.

#### D5 — Frontend tech stack: Chart.js 4.x UMD (vendored, ~80KB) + 纯手写 CSS/SVG

**Decision.** Chart.js 4.x UMD bundled minified (~80KB) 是唯一 vendored 第三方库。capacity gauge 用纯 SVG `<circle stroke-dasharray>` 手写（0KB），动态拓扑用纯 SVG DOM（4 节点 3 边，性能零压力，搜索确认 SVG 瓶颈在 5000+ 节点以上）。

**前端研究验证（2026-09-21）：**
- ECharts 最小 UMD ~135KB（比 Chart.js 大 50KB），原生有 gauge 但我们手写 SVG 搞定；其额外能力（地理、3D）对 console 不需要
- lightweight-charts ~45KB 更小，但只支持时间序列，做不了 pie 和 gauge
- Chart.js 4.x 原生支持 line + doughnut（pie），rolling window 60 data points 轻松 handle
- Vendoring 关键规则（经验 recall）：官方完整 UMD bundled minified、版本对齐 API、同源离线 + 降级 UI、LICENSE 伴随

**Scope.** Vendored files 在 `src/console/static/`。FastAPI StaticFiles mount。单页内联 HTML（无构建、无 SPA 框架）。

**Integration test update.** P13 把 `test_console.py` 的 "no external script src" 检查改为 "all script src 以 /static/ 开头"（验证同源离线）。

#### D6 — Load generator architecture: interactive tool, closed-loop concurrency pool + open-loop call-rate throttle

**Decision.** A new `tools/call_load_generator.py` replaces P9.5's capacity probe pattern. The generator has **two coupled but distinct** controls governed by **Little's Law** (`L = λW`, concurrent = rate × avg_duration — duration weights fixed by D7):

1. **Target concurrency (1-50)** — closed-loop pool ceiling. Tick loop (every ~500ms) tries to fill pool to this target. Primary control: caps max simultaneous calls regardless of anything else.
2. **Call rate (0.1-10 calls/sec)** — open-loop fill-speed throttle. Even if pool is below target, no more than `rate` new calls per second. Secondary control: limits how fast the pool refills.

**Precedence rule:** whichever constraint is more restrictive is binding. If `rate × avg_duration > target` → concurrency is binding, pool stabilizes at target. If `rate × avg_duration < target` → rate is binding, pool stabilizes at `rate × avg_duration` below target.

This is an **educational design**: the demo actively shows Little's Law at work. Reviewer drags concurrency up → pool grows and stabilizes. Reviewer drags rate down → pool drains below concurrency target (rate throttle is now binding). Console shows "约束因子" indicator so the reviewer understands the interaction.

**Call type toggles (T1-T6 from Phase 1 + F1-F4 from Phase 2):** enable/disable individual call types; disabled types are excluded from the generator's selection pool.

**Consequence.** The load generator is external to the AS processes — it uses the mock S-CSCF UAC pattern from `tools/chained_as_probe.py`. It is interactive (runs indefinitely, responds to console commands) rather than one-shot like P9.5.

#### D7 — Call model definition

**Decision.** The load generator's call population is defined as a mixed population of all Phase 1 + Phase 2 call types with weighted duration distribution. Caller and called number populations are taken from the existing demo data (allow-listed fleet prefix, block-listed numbers, high-rate numbers).

**Call types (10 types, drawn per grill validation):**

| # | Type | Origin | Result |
|---|------|--------|--------|
| T1 | +86 E.164 | translation AS | convert to 0-prefix, relay |
| T2 | 0-prefix national | translation AS | keep format, relay |
| T3 | 00-prefix international | translation AS | convert to +..., relay |
| T4 | 4-digit short code | translation AS | no match → 404 |
| T5 | reachable next hop | translation AS | 200 OK |
| T6 | unreachable next hop | translation AS | 3s timeout → fail |
| F1 | allow-listed caller | anti-fraud AS | relay |
| F2 | block-listed caller | anti-fraud AS | 608 Rejected |
| F3 | high-rate caller | anti-fraud AS | 608 Rejected |
| F4 | missing PAI | anti-fraud AS | fail-open → relay |

**Duration model (generator-controlled core behavior):**

| # | Weight | Description |
|---|--------|-------------|
| D1 Fast | 30% | Core answers 200 OK in 1s, BYE after 2s |
| D2 Medium | 50% | Core answers 200 OK in 2s, BYE after 8-15s |
| D3 Long | 15% | Core answers 200 OK in 2s, BYE after 20-30s |
| D4 Timeout | 5% | Core never answers → AS 3s no-answer tear-down |

**Console controls over this model:** target concurrency slider, call type toggles. Duration weights are not user-adjustable — stable defaults for demo consistency.

#### D8 — Phase 3 structure: two items, strict serial, ends at v1.0.0

**Decision.** Phase 3 consists of exactly two items, worked serially on `phase3` (new long-lived branch off `main`). Phase 3 ends at `v1.0.0` — the point at which the portfolio story becomes "we validate multi-call concurrency capability, and we show it on a real-time dashboard."

**Item 1 — P12 Call Load (backend):**
- Load generator tool (`tools/call_load_generator.py`)
- AS concurrent-call validation (isolation tests, timer independence tests)
- Per-call event stream enhancement (call_started, call_state_changed, call_ended, call_rejected)
- Console remains **old UI** during P12 (uses existing Call Trace view to watch events)

**Item 2 — P13 Enhanced Console (frontend):**
- Chart.js vendored
- AGENT.md §4.4 amended
- Console layout restructure (multi-panel grid)
- Live charts, dynamic SVG topology, capacity gauge
- Load generator controls (sliders + toggles)

Pipeline for both items keeps the full `AGENT.md` §5.1 ceremony (requirements → design → implementation → tests → acceptance) with read-only review gates.

### 11. What Phase 3 does not do

For clarity — Phase 3 explicitly does **not**:

1. Change `as_platform` library.
2. Implement Session Registry, Call State Machine, or Admission Control (D3).
3. Implement DNS SRV resolution (B3).
4. Change SIP signalling protocol handling (no new SIP headers, no message rewriting).
5. Add new AS use cases.
6. Publish capacity or benchmark numbers in documentation.

### 12. Detailed plan

See the companion document: [`docs/phase3-plan.md`](phase3-plan.md). It follows the structure of `phase2-plan.md` with full strategic decisions, work sequence, and acceptance criteria for each item.

### 13. Phase 3 in the gap register — and what's deferred

The revised gap table from Part A §7:

| Registered gap | Closed by Phase 3? | Notes |
|----------------|--------------------|-------|
| Chain carries no shared call context beyond pass-through headers | ✗ | Deferred to D3 (Phase 4+) |
| Single process, no persistence → Restart safety, session recovery, watchdog | ✗ | Deferred to D3/D2 |
| No admission control or back-pressure | ✗ | Deferred to D3 |
| Peer addresses are 127.0.0.1 ports; no DNS/SRV resolution | ✗ | Deferred to B3 |
| No HA / cluster / active-standby | ✗ | Deferred to D2 |
| Rules drift between environments | ✗ | Deferred to B2 |

Phase 3 closes **zero registered gaps** from Part A §7. It is **not** a gap-closing phase — it is a **display-capability phase**. This is the core departure from revision 1 (which was gap-first). The decision to deprioritize gap-closing for display value comes directly from `phase2-plan.md` D1: "portfolio piece, not a product."
