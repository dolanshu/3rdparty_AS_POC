# Requirements (SRS)

Capability list for the third-party Application Server POC. Every requirement is
traceable to an acceptance item in `docs/acceptance/criteria.md` and to the design in
`docs/architecture/hld.md` / `lld.md`. Behaviour changes must walk this chain
(`AGENT.md` section 13).

Status values: `planned` — not implemented yet · `partial` — partly in place ·
`done` — implemented and covered by an acceptance item.

## 1. Functional requirements

| ID | Requirement | Status | Milestone | Acceptance |
| --- | --- | --- | --- | --- |
| REQ-F-001 | The AS listens for SIP requests on the configured UDP address and port (`SIP_LISTEN_ADDRESS` / `SIP_LISTEN_PORT`) and accepts INVITE from the trunk. | done | M1 | ACC-M0-005, ACC-M1-001 |
| REQ-F-002 | The AS behaves as a B2BUA only: it terminates the incoming INVITE and originates a new INVITE towards the next hop. Redirect mode (`302`) is not implemented. | done | M1 | ACC-M1-001 |
| REQ-F-003 | The called number is translated according to the declarative rule set: E.164 ↔ national `0…`, short codes, international `00…`. | done | M0→M2 | ACC-M0-004, ACC-M2-001 |
| REQ-F-004 | A routing decision selects a next hop by priority and fails over to the next hop in the list. | done | M0→M2 | ACC-M0-004, ACC-M2-002 |
| REQ-F-005 | Rules are declarative YAML data under `config/`, validated on load and reloaded when the file changes (ADR-0004). | done | M0 | ACC-M0-004, ACC-M0-006 |
| REQ-F-006 | Error branches: no matching rule → `404`; policy rejection → `603`; caller abandons → `CANCEL`. | done | M0→M2 | ACC-M2-003 |
| REQ-F-007 | A request from a source address outside `ALLOWED_PEERS` is rejected with `403` and `AS-PEER-001`. | done | M1 | ACC-M1-003 |
| REQ-F-008 | SIP headers and the SDP body are passed through unmodified; only the Request-URI and the number format are rewritten. | done | M1 | ACC-M1-002 |
| REQ-F-009 | A complete call is driven: `INVITE → 100 → 180 → 200 OK → ACK → BYE`. | done | M1 | ACC-M1-001 |
| REQ-F-010 | Every log line carries timestamp, level, module, `call_id`, `direction`, `peer` and an event message. | done | M0 | ACC-M0-007 |
| REQ-F-011 | Counters for calls, dispositions, error codes, rule hits and peer status; health endpoint; graceful shutdown on `SIGTERM`/`SIGINT`. | done | M1→M3 | ACC-M1-004, ACC-M3-002, ACC-P8A-001 |
| REQ-F-012 | Console shows the live message flow, the rule that matched, the configuration, statistics and an SVG topology; rules are read-only. | done | M3 | ACC-M3-001 |
| REQ-F-013 | All configuration comes from the environment; switching from the mock to a real S-SBC is a configuration change only. | done | M0 | ACC-M0-005 |
| REQ-F-014 | Startup self-check (configuration schema, rules parse and validation, port availability, peer sanity) and fail-fast on invalid configuration. | done | M0 | ACC-M0-005 |
| REQ-F-015 | An internal error model maps `AS-*` codes to SIP status codes and log messages. | done | M0 | ACC-M0-007 |
| REQ-F-016 | The anti-fraud AS runs as a **second, independently runnable process** reusing the shared skeleton, with its own SIP listen ports, its own declarative data file under `config/` and its own console feed; it owns its lifecycle — a startup self-check and a stop path that cancels every timer it armed (D6, P8a lesson). | done | P8 | ACC-P8-001 |
| REQ-F-017 | On INVITE the AS inspects the **calling** party and produces a **verdict** — allow or reject. On allow the INVITE is relayed as a B2BUA: the Request-URI (never rewritten) and the SDP body are kept and the pass-through header set is copied, with **no header added**; on reject the call is answered from the UAS side. `Feature-Caps` is not in that pass-through set, so the `sip.608` declaration does not cross the AS (D4, ADR-0007 decision 6). | done | P8 | ACC-P8-002 |
| REQ-F-018 | The verdict is computed from caller reputation (a score that **decays over time**), a per-caller **call-rate window** and block/allow lists, read from a declared data file under `config/` that is validated on load (D4). | done | P8 | ACC-P8-003 |
| REQ-F-019 | A rejected call is answered on the trunk with `608` "Rejected" (RFC 8688) and **no `Call-Info`** header; on the allow path the relayed INVITE carries **no added header** (D5). | done | P8 | ACC-P8-002, ACC-P8-003 |
| REQ-F-020 | The mock S-SBC's UAC side declares `Feature-Caps: *;+sip.608` in its INVITE, and the AS plays no media announcement: the reject path stays signalling-only (D5, ADR-0006). | done | P8 | ACC-P8-003 |
| REQ-F-021 | The allow path still drives a full B2BUA relay (`INVITE → 100 → 180 → 200 OK → ACK → BYE`); the reject path is **UAS-only** and originates no second leg (P8 "Known collisions"). | done | P8 | ACC-P8-002 |
| REQ-F-022 | Cross-call anti-fraud state (the call-rate window and reputation) lives in a **process-level module** and never in the per-call `CallController` (D9). | done | P8 | ACC-P8-004 |
| REQ-F-023 | New `AS-FRAUD-*` error codes are added to the authoritative model in `src/as_app/errors.py` and mapped to SIP status codes and log messages (AGENT.md section 4.3). | done | P8 | ACC-P8-005 |
| REQ-F-024 | The verdict, its signals/score and the matched list entry are observable through counters, the Call-ID keyed trace and the console. | done | P8 | ACC-P8-005 |
| REQ-F-025 | The chained topology runs end to end via iFC orchestration: `S-SBC → AS-1 → S-CSCF → S-SBC → AS-2 → P-CSCF → terminating UAS`. An INVITE AS-1 **allows** triggers iFC #2 to AS-2, is translated there and completes (`INVITE → 180 → 200 OK → ACK → BYE`) through both AS instances (ADR-0014). | done | P9b | ACC-P9b-001 |
| REQ-F-026 | Chain order is configured in `ims_mock/chain_config`; `*_SBC_PEER_*` points at the S-SBC **return** port only (fallback when no `Route`). Neither AS imports the other (`AGENT.md` section 5). | done | P9b | ACC-P9b-001 |
| REQ-F-027 | A **reject** at AS-1 (`608`, REQ-F-019) short-circuits the chain: AS-2 and the terminating UAS never receive the call; `608` is relayed to the subscriber UAC (REQ-F-021). | done | P9b | ACC-P9b-004 |
| REQ-F-028 | The chained call is observable per instance: each AS writes its own Call-ID keyed trace; the demo makes **four** AS-leg `Call-ID` values visible (ADR-0014). | done | P9b | ACC-P9b-003 |
| REQ-F-029 | The skeleton shared by the two AS instances is **extracted into a library in a new repository** (checked out beside this one at `../as_platform`); both instances — `src/as_app/` (number translation) and `src/anti_fraud_as/` (anti-fraud) — become **users** of that library, and this repository becomes the library's **reference implementation** (D8). This is a structural refactor performed under an explicit plan: the `AGENT.md` section 14 rule 3 ("no unconfirmed refactors") waiver for P10 is recorded as approved in `docs/phase2-plan.md` section 8 item 2, and the plan is still written and reviewed **before any code moves**. | done | P10 | ACC-P10-001 |
| REQ-F-030 | The library is **independent of both use cases**: it imports neither `as_app` nor `anti_fraud_as`, so it carries the skeleton, not either use case. That independence is asserted by the library's own suite (`REQ-NF-021`). The one-way invariant that already holds is preserved and stays assertable — `src/as_app/**` does not import `anti_fraud_as` (`REQ-F-026`) — verified by `tests/unit/test_repository_baseline.py::test_as_app_does_not_import_the_anti_fraud_as`. | done | P10 | ACC-P10-002 |
| REQ-F-031 | The two AS instances remain **independent processes** and their externally observable behaviour is **unchanged** by the extraction: the same SIP signalling on the trunk, the same `AS-*` error codes and the same per-instance Call-ID keyed console feed. The extraction is a pure refactor with no wire-visible change, so the existing unit, integration and e2e layers stay green (the anti-regression requirement). | done | P10 | ACC-P10-003 |
| REQ-F-032 | This repository consumes the library through a **`path` dependency in `pyproject.toml`** (the library repository checked out beside it), so the `AGENT.md` section 10 guarantee *"clone → `uv sync` → `make demo`"* becomes *"clone **both** repositories side by side"*. This is a known and accepted cost of the extraction, recorded as an explicit exception rather than silently weakening the guarantee. | done | P10 | ACC-P10-004 |
| REQ-F-033 | The extraction is **staged, not all-or-nothing**: the skeleton moves into the library in a sequence of steps that each leave this repository building, linting and passing its three test layers, so `main` stays demonstrable at every step (D7, `AGENT.md` §10). A step that would leave the repository broken is not a valid step. | done | P10 | ACC-P10-007 |
| REQ-F-034 | `as_platform`'s Transport seam has a second implementation — `TlsTransport` — that terminates TLS/SIPS connections and bridges decrypted SIP messages to a local sippy UDP socket. `TlsTransport` accepts a certificate file path, a private key path and an optional CA certificate file path; it creates its own TLS listener on the configured port and a paired local UDP socket that `SipTransactionManager` binds to, so sippy's internal UDP machinery is untouched (AGENT.md §6, REQ-NF-003). TLS is **optional**: `UdpTransport` remains the default and the AS continues to run on UDP without any TLS configuration. | done | P11 | ACC-P11-002 |
| REQ-F-035 | `as_platform`'s StateStore seam has a second implementation — `RedisStateStore` — that persists caller state (call-rate window and reputation) in Redis, so state survives an AS process restart and can be shared by multiple AS instances. Redis is **optional**: `InMemoryStateStore` remains the default and `make demo`, the three test layers and CI run with no external service (AGENT.md §10, REQ-NF-008). | done | P11 | ACC-P11-003 |
| REQ-F-036 | `as_platform`'s `NextHop` value object `transport` field is extended from `Literal["udp"]` to `Literal["udp", "tls"]` so a B2BUA next hop can declare TLS as its transport (ADR-0003, REQ-F-002). | done | P11 | ACC-P11-004 |
| REQ-F-037 | `as_platform` ships a **capacity harness** as a library capability — a load generator that drives an AS stack through its callback interface at increasing offered concurrency levels, together with observation hooks that record the capacity boundary (the highest level where all calls complete within the configured timeout, plus any observable degradation such as event-loop gap growth). The harness is a library component, not an application: it is consumed by this repository (or by any other AS application) and its output is passed back to the caller, written to trace and counters, or discarded at the caller's choice. | done | P11 | ACC-P11-001 |
| REQ-F-038 | An **interactive load generator** (`tools/call_load_generator.py`) runs outside the AS processes and drives them through SIP INVITEs, maintaining a configurable concurrency pool (1–50) with a closed-loop leaky-bucket tick that fills the pool to the target at every ~500 ms interval and decrements it on each call end (BYE, CANCEL, timeout or 608 reject). The generator is **interactive** — it runs indefinitely, is started and stopped via REST API, and responds to configuration changes without a restart. | accepted | P12 | ACC-P12-001 |
| REQ-F-039 | The load generator's concurrency pool is coupled to a **call-rate throttle** (0.1–10 calls/sec, per second budget), so the two controls interact via Little's Law (`L = λW`). When `rate × avg_duration > target_concurrency` the pool stabilises at the target (concurrency is binding); when `rate × avg_duration < target_concurrency` it stabilises below target (rate is binding). The current binding constraint is exposed in the status endpoint. | accepted | P12 | ACC-P12-002 |
| REQ-F-040 | The load generator can be pointed at **either** AS singly (translation or anti-fraud) **or** at the chained topology (`S-CSCF#1 → S-SBC → anti-fraud → S-SBC → S-CSCF#2 → S-SBC → translation → S-SBC → S-CSCF → P-CSCF → UAS`, ADR-0014), selected by configuration. All 10 call types — translation types T1–T6 and anti-fraud types F1–F4 — are drawn per weighted random selection with a per-type **enabled/disabled toggle** from the console, so a demo can show only allow path, only reject path, or any mix. | accepted | P12 | ACC-P12-003 |
| REQ-F-041 | The load generator controls **per-call simulated behaviour** of the mock S-CSCF on the far side: four duration classes with fixed weights (D1 fast 30%, D2 medium 50%, D3 long 15%, D4 timeout 5%) — the mock answers 200 OK in each non-timeout class and sends BYE after the class's duration; D4 simulates a silent far end and lets the AS tear down after its 3 s no-answer timer. | accepted | P12 | ACC-P12-004 |
| REQ-F-042 | Both AS instances emit a **per-call event stream** on the internal API WebSocket — `call_started`, `call_state_changed` (with the new state), `call_ended` (reason: BYE, timeout, CANCEL, 608 reject), and `call_rejected_608` — every event keyed by the Call-ID and enriched with the call type (T1…F4) and the AS decision result. The load generator emits the same event shapes for pool changes (`pool_status_update` with current active/target concurrency and the binding constraint). The two streams are merged at the console into a single event feed that shows every call from generator side and both AS sides. | accepted | P12 | ACC-P12-005 |
| REQ-F-043 | When N concurrent calls run through the AS (10 recommended for P12 evidence, up to 50 in the generator), each `CallController` instance's lifecycle completes independently: one call's BYE does not terminate another's dialog, and one call's per-call timer (P8a tear-down timer, `REQ-NF-022`-adjacent) cancellation does not affect another's armed timer. This is a **validated architectural property**, not an assumed one — P12's test suite must prove it under load. | accepted | P12 | ACC-P12-006 |
| REQ-F-044 | The load generator exposes a small REST control surface: `POST /load/start`, `POST /load/stop`, `PUT /load/config` (`target_concurrency`, `call_rate`, `enabled_call_types`) and `GET /load/status` (current pool, binding constraint, enabled types). It also exposes a WebSocket feed that pushes `pool_status_update` and per-call generator-side events. Both surfaces are consumed by the console in P13. | accepted | P12 | ACC-P12-007 |
| REQ-F-045 | The console shows a **live call count over time** as a rolling-window line chart (default 30-second window, updates on every `pool_status_update` event). Implemented with vendored Chart.js (`REQ-F-050`). | accepted | P13 | ACC-P13-001 |
| REQ-F-046 | The console shows a **call-state distribution** as a pie/doughnut chart: active, completed, rejected_608, timeout. Updates on every per-call event from the AS event stream. | accepted | P13 | ACC-P13-002 |
| REQ-F-047 | The console shows a **capacity gauge** (active_calls / target_concurrency) — a doughnut-style progress indicator driven by `pool_status_update` events and reflecting the generator's current configuration. | accepted | P13 | ACC-P13-003 |
| REQ-F-048 | The console shows a **dynamic topology visualization** in SVG. P13 shipped one fixed 4-node diagram `S-SBC → anti-fraud AS → translation AS → S-SBC ret`; P14 (ACC-P14-003, ADR-0015) makes it **mode-aware**: `simple` dims the anti-fraud node (`S-SBC → translation AS → S-SBC ret`), `fraud` dims translation (`S-SBC → anti-fraud AS → S-SBC ret`), and `chained` switches to `Gen → S-SBC → anti-fraud AS → iFC → translation AS → UAS` with the generator ingress and the terminating UAS. **There is no "core" node**: the AS's outbound leg always ends at the S-SBC return side, and the called party is the terminating UAS behind P-CSCF. The two AS nodes are never a direct AS-to-AS SIP hop. Arrow thickness is proportional to active call count on that hop; arrow colour indicates the dominant state on that hop (green = active/completed, red = 608 rejections, orange = timeouts). | accepted | P13 | ACC-P13-004 |
| REQ-F-049 | The console exposes **load generator controls**: a target-concurrency slider (1–50), call-type toggles (T1–T6, F1–F4), and Start/Stop buttons. Controls call the generator's REST API (`PUT /load/config`, `POST /load/start|stop`) and update from `pool_status_update` events so the UI never drifts from generator state. | accepted | P13 | ACC-P13-005 |
| REQ-F-050 | The console uses a **vendored Chart.js UMD bundle** served from `/static/` — Chart.js 4.x, ~16 KB minified, MIT license, committed to the repository under `src/console/static/`. No CDN reference, no npm, no build step. The license file ships alongside the bundle (ADR-0011, `AGENT.md` §4.4 amendment). | accepted | P13 | ACC-P13-006 |
| REQ-F-051 | `scripts/phase3-demo.sh full` runs the **P9b iFC chain** with multi-process AS instances and `python -m ims_mock.external_runtime`; both AS peer to the S-SBC return port, not to core directly (ADR-0015). | done | P14 | ACC-P14-001 |
| REQ-F-052 | The load generator exposes **`topology`** (`simple`, `fraud`, `chained`) and **`ingress_port`** on `GET /load/status` and accepts `topology` on `PUT /load/config` (completes REQ-F-040 for the interactive demo). | done | P14 | ACC-P14-002 |
| REQ-F-053 | The console Dashboard shows a **topology mode badge** and switches between simple and chained SVG layouts; inactive nodes are dimmed in single-AS modes (REQ-F-048 extension). | done | P14 | ACC-P14-003 |
| REQ-F-054 | When `--fraud-api-url` is configured, the console opens **both** AS `/ws/p12/events` streams and shows dual instance health (REQ-F-042 extension). | done | P14 | ACC-P14-004 |
| REQ-F-055 | Call-type toggles are **topology-aware**: T1–T6 disabled in `fraud` mode, F1–F4 disabled in `simple` mode; server rejects invalid sets with HTTP 400. | done | P14 | ACC-P14-005 |

## 2. Non-functional requirements

| ID | Requirement | Status | Milestone | Acceptance |
| --- | --- | --- | --- | --- |
| REQ-NF-001 | Signalling only: no RTP, no media anchoring, no MRF (ADR-0006). | done | M0 | ACC-M0-008 |
| REQ-NF-002 | UDP is the only transport **on this POC's trunk**; TCP and TLS are not deployed here (ADR-0003). The platform library's pluggable `Transport` seam ships a `TlsTransport` (P11, ADR-0010) that no AS in this repository uses. | done | M0 | ACC-M0-008 |
| REQ-NF-003 | Python 3.10 and sippy 2.4.2, pinned; the stack is verified by running it, not by assumption. | done | M0 | ACC-M0-002 |
| REQ-NF-004 | Routing and translation are pure functions with no sockets, no global state and no clock, tested by the unit layer; three test layers are green. | done | M0 | ACC-M0-009 |
| REQ-NF-005 | Every log line and console event is correlated by the SIP Call-ID. | done | M0→M3 | ACC-M0-007, ACC-M3-001 |
| REQ-NF-006 | No secrets, certificates or real traffic captures are committed; payload logging is explicit and off by default. | done | M0 | ACC-M0-010 |
| REQ-NF-007 | The repository reads as a telecom-grade deliverable: skeleton, documentation set, ADRs, acceptance evidence and production gap register (AGENT.md section 4). | done | M0 | ACC-M0-001, ACC-M0-003 |
| REQ-NF-008 | A clean checkout runs: `uv sync` → `make lint` / `make test`; `make demo` places a real call. | done | M0 | ACC-M0-002, ACC-M0-009, ACC-M4-002 |
| REQ-NF-009 | No performance or capacity claims: no call rate, latency or capacity target is defined for the POC. | done | M0 | ACC-M0-011 |
| REQ-NF-010 | Console uses no **CDN-loaded** third-party front-end library and no build step. The single exception is the locally vendored Chart.js UMD bundle admitted by ADR-0011 (P13, REQ-F-050); it is committed to the repository and served from `/static/`, never fetched from a network. | done | M0 | ACC-M3-001 |
| REQ-NF-011 | The verdict is a **pure function**: no sockets, no global state and no clock access inside the engine (time is injected), unit-testable without a network (AGENT.md section 12, REQ-NF-004 precedent). | done | P8 | ACC-P8-004 |
| REQ-NF-012 | Cross-call anti-fraud state is **in memory**; a restart loses it. This is a registered POC gap, closed in P11 by the pluggable state store (D9). | done | P8 | ACC-P8-004 |
| REQ-NF-013 | No media is played. A real UAC that does not declare `sip.608` would require a media announcement; this is a registered POC gap, not a hidden defect (D5, ADR-0006). | done | P8 | ACC-P8-003 |
| REQ-NF-014 | Configuration is through environment variables only, declared in `.env.example`; **no new third-party dependency** is added (AGENT.md section 8). | done | P8 | ACC-P8-001 |
| REQ-NF-015 | The `608` reject path is verified **by running sippy**, not assumed (AGENT.md section 6). | done | P8 | ACC-P8-006 |
| REQ-NF-016 | Cross-AS Call-ID correlation is **not solved**: four AS-leg `Call-ID` values on the allow path; each instance keys its trace on its own trunk leg only. Gap made visible, not hidden (ADR-0014). | done | P9b | ACC-P9b-003 |
| REQ-NF-017 | The chained topology is demonstrated by **`make demo-chained`** (`tools/demo_chained_call.py`), wired via `ims_mock` orchestrator, not peer-to-peer env vars (ADR-0014). | done | P9b | ACC-P9b-005 |
| REQ-NF-018 | P10 friction: the POC requires an **IMS-side orchestrator mock**; neither AS knows about the chain (ADR-0014, `docs/production-gaps.md` P9b row). | done | P9b | ACC-P9b-005 |
| REQ-NF-019 | The new repository is a **library, not a running service**, so it follows the **library documentation standard** of D8 — an **API reference**, an **integration guide** and a **compatibility matrix** — and does **not** copy this repository's application document set (the ~24 documents of `docs/`, including the operations set `deployment` / `runbook` / `troubleshooting`, which does not apply to a library). It is **not** a uv workspace monorepo (D8). | done | P10 | ACC-P10-005 |
| REQ-NF-020 | The two pluggable dimensions P11 verifies (**transport**: UDP/TLS; **state store**: in-memory/Redis) and P11's **capacity harness** (D10) are **enabled by, but not built in, P10**: the extraction leaves those boundaries pluggable and adds no second transport, no external store and no load harness. The in-memory cross-call state (`REQ-NF-012`) remains the only implementation until P11 (D9). | done | P10 | ACC-P10-006 |
| REQ-NF-021 | The new repository carries **its own test suite and its own gate** (`ruff` format and lint, `mypy`, `pytest`), so a change to the library is verifiable **where the library lives** rather than only through this repository's suite. Its suite covers the pure helpers and the sippy adapter boundary, plus the library-level independence assertion of `REQ-F-030`. The three layers of `AGENT.md` §11 are the **application's** layers (AS and mock S-SBC on UDP, a full call) and do not transfer to a library, which is why this row states a library-shaped suite instead of restating them (D8: the new repository follows the library standard, not the application standard). | done | P10 | ACC-P10-008 |
| REQ-NF-022 | sippy 2.4.2 **does not support SIP TLS or TCP transport** — confirmed by reading `SipTransactionManager.newTransaction()` which handles only `udp`, `ws`, `wss` and raises on anything else (AGENT.md §6 forbids modifying sippy source). The TLS bridge approach (REQ-F-034) terminates TLS at the Transport seam layer with a Python `ssl` + `socket` listener, independently of sippy. This limitation is recorded as a verified fact and the bridge is what `TlsTransport` implements. | done | P11 | ACC-P11-002 |
| REQ-NF-023 | Redis I/O must not happen inside a sippy callback (AGENT.md §6 — `ED2.loop()` must stay event-driven and non-blocking; any blocking I/O stalls the whole SIP stack). `RedisStateStore` bridges its synchronous `read`/`write` calls to sippy threads via a background-worker queue pattern similar to the existing rule-reload precedent: the sippy callback schedules the I/O, a dedicated worker thread performs it, and the result is passed back to sippy via a loop-owned timer or callback injection that sippy already provides. | done | P11 | ACC-P11-003 |
| REQ-NF-024 | `InMemoryStateStore` is the default at every `BaseAsStack` site and at every test layer, so `make demo` and the three application test layers plus CI remain fully self-contained. Redis is enabled only when the application's configuration explicitly selects it (for example, via an environment variable), and its absence in an application that does not select it is not an error (D9: in-memory stays the default). | done | P11 | ACC-P11-004 |
| REQ-NF-025 | The capacity harness does **not publish benchmark numbers** (D10, REQ-NF-009). Its output — call completion counts, loop gap samples, any observable degradation at a given offered level — is passed back to the caller, logged as trace events, or written to counters. No number from a harness run appears in README, `docs/`, CHANGELOG or acceptance evidence as a "this AS handles X calls per second" claim; the harness is a measurement capability, not a performance benchmark. | done | P11 | ACC-P11-005 |
| REQ-NF-026 | TLS certificates and private keys are never committed (`AGENT.md §9`). The repository ships only a **certificate-generation script** (openssl-based) and a README section explaining how to create self-signed certificates locally. The script is excluded from the gate (no `make certs` target) because certificate generation is a one-off pre-deployment step. | done | P11 | ACC-P11-006 |
| REQ-NF-027 | **Phase 3 (P12 + P13) does not modify the `as_platform` library.** No new Transport, StateStore, error-code family, or BaseAsStack method moves into `../as_platform`. The event stream emissions `REQ-F-042` requests are AS-local — they extend the existing internal_api WebSocket handler that each AS instance already has (`as_app` and `anti_fraud_as`), not the library's skeleton. | accepted | P12 | ACC-P12-008 |
| REQ-NF-028 | Each AS instance (translation and anti-fraud) runs as its **own process with its own sippy `ED2` event loop**. The concurrent call isolation `REQ-F-043` validates holds **per-AS**, not cross-AS: each AS's process handles multiple concurrent calls independently. Phase 2 P9 already proved chained isolation; P12 proves **within-AS** concurrent isolation for the first time. | accepted | P12 | ACC-P12-009 |
| REQ-NF-029 | The load generator is an **external tool, not an AS component**. It talks to AS processes only via SIP (INVITE from a mock S-CSCF) and observes via event streams (`REQ-F-042`). It does not import `as_platform`, `src/as_app` or `src/anti_fraud_as`. Running the generator is an **additional** process that `make demo` does not launch — `make demo` stays self-contained for Phase 3's development cycle. | accepted | P12 | ACC-P12-010 |
| REQ-NF-030 | P12's integration and e2e tests exercise **genuine concurrent load** — not sequential one-call-at-a-time that happens to run in the same test file. The test suite must prove the `REQ-F-043` isolation property by: (a) launching N (≥ 10) concurrent calls through the AS process, (b) verifying each call reaches its own independent end, and (c) asserting that one call's timer cancellation did not affect any other call's armed timer (`REQ-F-043` is the claim, and a test that launches one call at a time is not a proof of that claim). | accepted | P12 | ACC-P12-011 |

## 3. Traceability notes

- `REQ-F-003` and `REQ-F-004` are implemented as pure functions in
  `src/as_app/routing/engine.py`; the sippy glue that applies them to a Request-URI is
  `CallController.apply_call_policy` in `src/as_app/call_controller.py` (M2).
- `REQ-NF-009` is a deliberate non-goal, registered in `docs/production-gaps.md`.
- **Graceful shutdown (P8a, 2026-09-18).** `REQ-F-011` covers "graceful shutdown on
  `SIGTERM`/`SIGINT`"; that requirement text is **unchanged** — the capability it asks for
  was already delivered in M1, and this item only removes a defect from the path that
  implements it. Before the fix, stopping the stack left the per-transaction retransmission
  timers armed in sippy's process-wide `ED2` loop, so an INVITE still awaiting an answer
  kept retransmitting into a torn-down manager and raised
  `TypeError: 'NoneType' object is not subscriptable`. `AsStack.stop()` now cancels them —
  and the per-call no-answer timers — before sippy's own
  `SipTransactionManager.shutdown()` (see `docs/architecture/lld.md` §3.2 and §5). Traced
  by **ACC-P8A-001**, which asserts the property directly; the previously flaky failover
  test is the symptom, not the guard. No wire behaviour changed, so no entry in
  `docs/specs/` and no message sample is affected.
- **P8 anti-fraud AS — requirements stage (2026-09-19).** `REQ-F-016 … REQ-F-024` and
  `REQ-NF-011 … REQ-NF-015` are P8's own rows; no Phase 1 requirement is changed. Two
  boundaries are stated here because they are the item's most likely failure modes.
  **State ownership (D9):** cross-call state — the per-caller call-rate window and
  reputation — lives in a process-level module, never in the per-call `CallController`,
  because a window held there would contain exactly one entry per call and fail silently
  while single-call unit tests still pass (`REQ-F-022`, `REQ-NF-012`). **Purity
  (`REQ-NF-011`):** the verdict itself is a pure function — no sockets, no global state, no
  clock access, time injected — so it is unit-testable without a network, matching the
  `REQ-NF-004` precedent for translation and routing. **Error model (`REQ-F-023`):** the new
  `AS-FRAUD-*` codes live in the one authoritative model in `src/as_app/errors.py`, mapped to
  SIP status codes and log messages per `AGENT.md` section 4.3, as the existing
  `AS-CFG-* / AS-RULE-* / AS-ROUTE-* / AS-PEER-*` families do. The `608` reject path is
  validated by an sippy probe (`REQ-NF-015`); ADR-0007 and the HLD/LLD deltas are the next
  pipeline stage (`docs/phase2-plan.md` section 5.1) and are not written here. **Reject path
  vs "B2BUA only" (`REQ-F-021`).** The reject path terminates the incoming INVITE and
  answers it from the UAS side, originating no second leg; this is the behaviour
  `docs/phase2-plan.md` section 3 P8 ("Known collisions") already sanctions as *"UAS
  behaviour, not B2BUA"*, so `REQ-F-021` is a documented, approved deviation limited to the
  reject path, while `REQ-F-002`'s "B2BUA only" statement continues to describe the
  relay/allow path. This requirements-stage review gate raised these three points —
  reputation decay, the second process's stop path and this reject-path reconciliation —
  and they were folded into `REQ-F-016`, `REQ-F-018` and this note here.
- **P9 chained demo — requirements stage (2026-09-19).** `REQ-F-025 … REQ-F-028` and
  `REQ-NF-016 … REQ-NF-018` are P9's own rows; no Phase 1 or P8 requirement is changed.
  **Chaining is configuration, not code (D6, `REQ-F-026`).** The plan's implementation note
  recorded that no iFC emulation was needed in the mock and that pointing AS-1's next hop at
  AS-2's listen address was a peer/catalogue setting. **That wiring is superseded by P9b /
  ADR-0014 (2026-09-23):** the chain is now driven by the S-CSCF iFC orchestrator in
  `src/ims_mock/`, no AS ever addresses another AS, each AS receives its own trunk INVITE
  from the S-SBC forward side and returns its outbound INVITE to the top `Route` on the
  S-SBC return side, and `*_SBC_PEER_*` is only the fallback for a trunk INVITE that carries
  no `Route`. **Structural change (`REQ-NF-017`).** P9
  introduces a **new run command** — a chained-demo entry point mirroring `make demo` /
  `make demo-fraud`. Under `AGENT.md` section 13 a changed run command is a structural
  change, so the implementation commit must update `AGENT.md` section 10, `README.md` and
  `docs/README.md` in the same commit. The chained topology needs **no new environment
  variable and no new port**: the two AS listen ports (`5060` / `5062`) already differ
  precisely so both instances can run on one host (plan section 6).   **Known issue
  (`REQ-NF-016`, `REQ-F-028`).** Two B2BUAs in series mean one `Call-ID` per leg — four
  AS-leg values on the implemented iFC chain (`X`, `X-b2b_1`, `Z`, `Z-b2b_1`; ADR-0014
  decision 4). Each AS terminates the incoming INVITE and originates its own second leg, and
  `Call-ID` is regenerated rather than passed through (`src/as_app/sip_adapter.py`,
  `PASSTHROUGH_HEADERS`), so cross-AS correlation is unsolved and is registered as a POC gap
  rather than assumed away.
  **Deliberate output (`REQ-NF-018`).** The friction the chain exposes is P10's primary
  input and is recorded at the item's close (plan section 5.4). The HLD/LLD deltas and any
  probe are the next pipeline stage (plan section 5.1) and are not written here; the
  `ACC-P9-*` items are created in the acceptance stage, as `ACC-P8-*` were.
- **P10 platform extraction — requirements stage (2026-09-19).** `REQ-F-029 … REQ-F-032` and
  `REQ-NF-019 … REQ-NF-020` are P10's own rows; **no Phase 1, P8 or P9 requirement is
  changed**. The extraction is a structural refactor of `src/as_app/` and `src/anti_fraud_as/`
  into a library in a new repository (`../as_platform`); three drivers are already on record
  and are not re-litigated here — the pluggable state store (D9), the skeleton friction the
  chained demo surfaced (`REQ-NF-018`, plan section 3 P9), and the capacity/back-pressure
  constraints (D10). The `AGENT.md` section 14 rule 3 approval and the D8 library standard are
  cited in `REQ-F-029` and `REQ-NF-019` respectively; the plan itself is written first and
  reviewed before any code moves (plan section 8 item 2). Three rows are the non-obvious ones.
  **Behaviour unchanged (`REQ-F-031`) is the most important row.** The whole point of the
  extraction is that nothing observable moves: both AS instances stay independent processes,
  the SIP signalling, the `AS-*` error codes and the per-instance console feed are identical,
  and the existing three-layer suite (the layer counts are on record in
  `docs/acceptance/report.md`) stays green. If that suite has to change to accommodate the
  extraction, the extraction is wrong, not the tests — with one bounded exception, recorded in
  ADR-0009 decision 3: a unit test that reads, iterates or annotates a **genuinely moved** enum
  member may be repointed at the family enum that now owns it. No assertion's expected value
  changes, and the single uniqueness/status-coverage test is strengthened in scope. The
  extraction may not change what a test asserts.
  **The one-way independence (`REQ-F-030`) has a direction.** `src/anti_fraud_as/**` imports
  `as_app` in several places by design (ADR-0007 decision 9) — the reuse of the
  use-case-agnostic skeleton — so the invariant that is assertable, and the one the library
  must preserve, is `src/as_app/**` ↛ `anti_fraud_as`; the library itself imports neither use
  case. `REQ-F-026` already carries the `neither AS imports the other` wording and its
  assertable direction is registered as plan section 7 item 10; this row states the direction
  explicitly for the library rather than re-opening that frozen requirement. **The `path`
  dependency (`REQ-F-032`) is a deliberate, accepted exception.** Consuming the library through
  `pyproject.toml` means this repository no longer satisfies `AGENT.md` section 10's *"clone →
  `uv sync` → `make demo`"* on its own; the guarantee is restated as *"clone both repositories
  side by side"*. It is recorded as an exception so a later reader does not read the weaker
  guarantee as a defect, and the exact `pyproject.toml` mechanism belongs to P10's
  implementation stage, not here. `REQ-NF-019` keeps the new repository on the library standard
  of D8 (API reference / integration guide / compatibility matrix) instead of copying this
  repository's application document set; `REQ-NF-020` scopes P10 so it **enables** P11's
  pluggable transport, pluggable state store and capacity harness without **building** any of
  them. The HLD/LLD deltas, the ADR and any probe are the next pipeline stage (plan section
  5.1) and are not written here; the `ACC-P10-*` items are created in the acceptance stage, as
  `ACC-P8-*` and `ACC-P9-*` were. **Requirements-stage review gate (plan section 5.2).** Two
  of the rows above came out of that gate's read-only review of this stage and were fixed
  inside the stage: `REQ-F-033` (the extraction is staged, so this repository stays
  demonstrable at every step — D7, `AGENT.md` §10) and `REQ-NF-021` (the new repository carries
  its own test suite and its own gate, so a change to the library is verifiable where the
  library lives). The same gate found that `REQ-F-030`'s library-level independence claim
  carried no named verification, so that row was amended to cite the library's own suite. These
  were findings of the section 5.2 review gate, fixed inside the stage; the gate's verdict is
  recorded in `docs/phase2-plan.md`, not here.
- **P10 platform extraction — design stage (2026-09-19), the `REQ-F-023` delta.** `REQ-F-023`'s
  text is **unchanged**: it was true when written (P8 added the `AS-FRAUD-*` codes to the
  then-single authoritative model), and a stage may not reword a frozen requirement (plan
  section 5.2). After P10 the authoritative *model* is the **library's mechanism** — the
  memberless `ErrorCode` base, `SIP_PHRASES`, `sip_status_for` and `AsError` in
  `as_platform.errors` — while the `AS-FRAUD-*` family lives in `src/anti_fraud_as/errors.py`
  and the translation families (`AS-RULE-*`, `AS-ROUTE-*`) stay in `src/as_app/errors.py`
  (ADR-0009 decision 3). Every code, SIP status and log message is **unchanged**, so the row's
  intent — one model, no second error vocabulary, codes mapped to SIP status and log message —
  holds; only the location the row names has moved. This is the same way P8a records the
  `REQ-F-011` delta: the requirement text is unchanged and the note carries the change.
  `AGENT.md` section 4.3 is a structural document, not a frozen requirement, and is updated in
  P10's implementation commit to name the library mechanism and the three families (`AGENT.md`
  section 13).
- Milestones M0–M3 are delivered, so no requirement above is left `planned` or `partial`
  for want of a milestone. The `docker compose` stack (both AS instances, two mocks and the
  console) is validated with `docker compose config`; its SIP path still carries the
  `ALLOWED_PEERS` issue tracked in `docs/roadmap.md` (M1 open items), so a call through
  compose is not demonstrated.

- **P11 platform verification — requirements stage (2026-09-20).** `REQ-F-034 … REQ-F-037` and
  `REQ-NF-022 … REQ-NF-026` are P11's own rows; no Phase 1, P8, P9 or P10 requirement is
  changed — the one exception is that `REQ-NF-002` ("UDP is the only transport; TCP and
  TLS are not implemented") becomes historically inaccurate after P11 ships `TlsTransport`
  and is **not rewritten here**; its rewording is left to a later housekeeping item, the
  same pattern as P10 leaving REQ-F-023's location claim to the implementation stage
  (see §3 note for that row). Four boundaries are stated here because they are P11's most
  likely failure modes.

  **sippy limitation is the reason, not an afterthought (REQ-NF-022).** P11 starts with a
  probe of sippy's TLS support — `AGENT.md` §14 forbids assuming. The probe result is
  decisive: `SipTransactionManager.newTransaction()` handles only `udp`, `ws`, `wss` and
  raises `RuntimeError` on anything else; there is no `Tcp_server`, no `Tls_server`, and
  `SipConf` hard-codes `default_transport = 'udp'`. WSS (WebSocket Secure) is the only path
  in sippy that uses TLS, but WebSocket is not SIP and both sides would need WebSocket
  endpoints — a different transport altogether. So `TlsTransport` is designed as an
  **external bridge**: Python `ssl` + `socket` creates a TLS listener at the configured
  port, sippy's `SipTransactionManager` binds to a paired local UDP socket, and
  `TlsTransport` bridges encrypted SIP ↔ decrypted SIP across the gap. This is architecturally
  honest: in a real deployment TLS often terminates at a load balancer or SIP proxy in front
  of the AS. And it proves the Transport seam is pluggable — the entire point of P11.

  **Redis I/O must not block the event loop (REQ-NF-023).** `ED2.loop()` is single-threaded
  and blocking I/O inside a sippy callback stalls every transaction. The existing
  rule-reload timer — a loop-owned `Timeout` that polls a file on disk — is the precedent:
  I/O happens outside the sippy callback. For Redis, a background-worker queue matches that
  pattern: sippy callbacks only enqueue work, a dedicated thread runs the Redis client,
  and results are handed back through a sippy-compatible mechanism (scheduled callback or
  `ED2` event injection that sippy already exposes). Synchronous `read`/`write` signatures
  are preserved at the StateStore seam — the application does not change — but the
  `RedisStateStore` implementation handles the non-blocking bridge privately.

  **In-memory stays the default (REQ-NF-024).** `make demo`, the three application test
  layers and CI must keep running with no external service (AGENT.md §10), so
  `InMemoryStateStore` remains what every `BaseAsStack` gets unless the application
  explicitly wires a different store. Redis is a deployment choice, not a development
  requirement — matching D9 and P8's gap that P11 closes.

  **Harness is a library component, not a benchmark (REQ-F-037, REQ-NF-025).** P9.5 ran
  a read-only capacity probe and found `timerB` is the effective give-up edge, armed
  transaction populations grow with burst × hops, and no back-pressure exists inside the
  configured range. P11's harness turns that probe into a first-class library capability
  but stays deliberately silent on absolute numbers (D10, REQ-NF-009). It drives an AS
  stack at increasing offered concurrency and reports — per level — whether all calls
  completed within the configured timeout, whether the event-loop gap grew, and whether
  any admission or failure boundary became observable. Those observations go to trace,
  counters or the caller's callback — never to README as a "we handle X calls per second"
  claim.

  **TLS certificates are never committed (REQ-NF-026).** A shell script that generates
  self-signed certificates locally is shipped in the library; the private key and
  certificate are both gitignored and generated on demand. This mirrors `AGENT.md §9`
  which already forbids secrets in the repository.

  **Where these rows live.** P11's implementation lives in the `as_platform` repository
  (`../as_platform`, checked out beside this one — §4 table of `docs/phase2-plan.md`), and
  this repository remains the platform's reference implementation that P11's new transports
  and new store are demonstrated against. The rows above describe the library itself;
  nothing in the application-facing rows changes behaviour in `src/as_app/` or
  `src/anti_fraud_as/`.

- **P12 Call Load capability — requirements stage (2026-09-21).** `REQ-F-038 … REQ-F-044`
  and `REQ-NF-027 … REQ-NF-030` are P12's own rows; **no earlier requirement is changed**.
  P11 (`REQ-F-034 … REQ-F-037` / `REQ-NF-022 … REQ-NF-026`) remains `planned` in its rows
  because P11 was merged into `main` with P8–P11 content — updating those statuses is a
  Phase 3 housekeeping item, not P12's job. Five boundaries are stated here because they
  are P12's most likely failure modes.

  **As-library isolation is the structural constraint (`REQ-NF-027`, D1).** Phase 3 is
  the first phase since P10 that **does not move anything into `as_platform`** — the
  deliberate break from P10/P11 which together transferred Transport, StateStore and
  capacity harness into the library. The event stream emissions `REQ-F-042` requests are
  AS-local extensions to each AS instance's existing internal_api WebSocket handler
  (`as_app` and `anti_fraud_as`), not new library methods. This constraint keeps the
  library stable while the application grows around it.

  **Two controls, one mathematical truth (`REQ-F-039`, D6).** The maintainer's original
  grill pointed out that `target_concurrency` and `call_rate` are not independent —
  Little's Law (`L = λW`) couples them once `avg_duration` is fixed by the duration
  weights. The decision to keep **both** controls rather than collapse them was made in
  the design: the two controls are the pool ceiling and the refill throttle, not two
  sliders on the same quantity. The binding constraint is exposed in the status endpoint
  so the console (P13) can show which control is actively limiting the pool — a feature
  that turns the demo from "here are numbers" into "watch Little's Law at work".

  **Validation vs assumption (`REQ-F-043`, `REQ-NF-030`).** P12's whole reason for being
  is that Phase 1/2 **never exercised** concurrent call isolation — every demo and every
  test ran one call at a time. The architecture **should** be correct (each
  `CallController` is an independent sippy callback, no shared mutable state beyond the
  `ED2` loop), but P12 cannot ship "we assume it works". The requirement text
  deliberately uses the word **validated** — P12's tests must launch N concurrent calls
  (≥ 10 recommended) and assert isolation properties under load. A test that launches
  one call at a time and checks it ends correctly is not a proof of concurrent
  isolation. The P8a timer cancellation property (`REQ-F-043`'s second clause) is the
  sharpest edge here: P8a fixed `as_app/call_controller.py`'s timer population bug,
  but P8a's tests were single-call. P12 runs N calls with unreachable next hops and
  asserts that one call's tear-down timer cancellation doesn't reach another's armed
  timer — this is a new test shape, not a rerun of P8a.

  **Generator is external, not embedded (`REQ-NF-029`).** P9.5's capacity probe was a
  Python script that drove AS instances through the library's callback interface. P12's
  generator talks via **SIP** — it's a mock S-CSCF UAC that sends INVITEs to the AS's
  SIP listen port. This is a deliberate boundary: the generator does not import any AS
  code, runs in its own process, and can be pointed at any SIP-speaking implementation,
  not just this repository. It also means `make demo` stays self-contained — P12's
  generator is an **additional** process for interactive demos, not a required component
  of the development cycle or CI.

  **What P12 does NOT change.** Phase 3's purpose statement (`docs/post-phase2-directions.md`
  Part B D1) says "demonstrate what already exists, not invent what doesn't". P12 does not
  change SIP signalling, routing rules, number translation, anti-fraud verdict logic,
  the chained topology wiring, or any sippy behaviour. It validates these under load
  and adds a tool to show that validation. The gap table from Part A §7 still shows
  Phase 3 closing **zero** registered gaps — that is an explicit decision, not an
  oversight.
