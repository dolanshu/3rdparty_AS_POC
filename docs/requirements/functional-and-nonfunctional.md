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
| REQ-F-025 | The chained topology `SBC → AS-1 (anti-fraud) → AS-2 (number translation) → core` runs end to end: an INVITE AS-1 **allows** is relayed to AS-2, translated there and routed to the core, driving a complete call (`INVITE → 100 → 180 → 200 OK → ACK → BYE`) through both AS instances (D6). | done | P9 | ACC-P9-001 |
| REQ-F-026 | The two AS instances are chained by **configuration only**: AS-1's next hop is set to AS-2's SIP listen address and AS-2's routing catalogue selects the core. No iFC emulation is added to the mock, and neither AS imports the other — they stay independent processes (D6, `AGENT.md` section 5). | done | P9 | ACC-P9-001 |
| REQ-F-027 | A **reject** at AS-1 (`608`, REQ-F-019) short-circuits the chain: AS-2 and the core never receive the call, because the reject path originates no second leg (REQ-F-021). | done | P9 | ACC-P9-002 |
| REQ-F-028 | The chained call is observable per instance: each AS writes its own Call-ID keyed trace and console feed, and the demo makes the two Call-IDs the two B2BUAs in series produce visible rather than hiding them. | done | P9 | ACC-P9-003 |
| REQ-F-029 | The skeleton shared by the two AS instances is **extracted into a library in a new repository** (checked out beside this one at `../as_platform`); both instances — `src/as_app/` (number translation) and `src/anti_fraud_as/` (anti-fraud) — become **users** of that library, and this repository becomes the library's **reference implementation** (D8). This is a structural refactor performed under an explicit plan: the `AGENT.md` section 14 rule 3 ("no unconfirmed refactors") waiver for P10 is recorded as approved in `docs/phase2-plan.md` section 8 item 2, and the plan is still written and reviewed **before any code moves**. | done | P10 | ACC-P10-001 |
| REQ-F-030 | The library is **independent of both use cases**: it imports neither `as_app` nor `anti_fraud_as`, so it carries the skeleton, not either use case. That independence is asserted by the library's own suite (`REQ-NF-021`). The one-way invariant that already holds is preserved and stays assertable — `src/as_app/**` does not import `anti_fraud_as` (`REQ-F-026`) — verified by `tests/unit/test_repository_baseline.py::test_as_app_does_not_import_the_anti_fraud_as`. | done | P10 | ACC-P10-002 |
| REQ-F-031 | The two AS instances remain **independent processes** and their externally observable behaviour is **unchanged** by the extraction: the same SIP signalling on the trunk, the same `AS-*` error codes and the same per-instance Call-ID keyed console feed. The extraction is a pure refactor with no wire-visible change, so the existing unit, integration and e2e layers stay green (the anti-regression requirement). | done | P10 | ACC-P10-003 |
| REQ-F-032 | This repository consumes the library through a **`path` dependency in `pyproject.toml`** (the library repository checked out beside it), so the `AGENT.md` section 10 guarantee *"clone → `uv sync` → `make demo`"* becomes *"clone **both** repositories side by side"*. This is a known and accepted cost of the extraction, recorded as an explicit exception rather than silently weakening the guarantee. | done | P10 | ACC-P10-004 |
| REQ-F-033 | The extraction is **staged, not all-or-nothing**: the skeleton moves into the library in a sequence of steps that each leave this repository building, linting and passing its three test layers, so `main` stays demonstrable at every step (D7, `AGENT.md` §10). A step that would leave the repository broken is not a valid step. | done | P10 | ACC-P10-007 |

## 2. Non-functional requirements

| ID | Requirement | Status | Milestone | Acceptance |
| --- | --- | --- | --- | --- |
| REQ-NF-001 | Signalling only: no RTP, no media anchoring, no MRF (ADR-0006). | done | M0 | ACC-M0-008 |
| REQ-NF-002 | UDP is the only transport; TCP and TLS are not implemented (ADR-0003). | done | M0 | ACC-M0-008 |
| REQ-NF-003 | Python 3.10 and sippy 2.4.2, pinned; the stack is verified by running it, not by assumption. | done | M0 | ACC-M0-002 |
| REQ-NF-004 | Routing and translation are pure functions with no sockets, no global state and no clock, tested by the unit layer; three test layers are green. | done | M0 | ACC-M0-009 |
| REQ-NF-005 | Every log line and console event is correlated by the SIP Call-ID. | done | M0→M3 | ACC-M0-007, ACC-M3-001 |
| REQ-NF-006 | No secrets, certificates or real traffic captures are committed; payload logging is explicit and off by default. | done | M0 | ACC-M0-010 |
| REQ-NF-007 | The repository reads as a telecom-grade deliverable: skeleton, documentation set, ADRs, acceptance evidence and production gap register (AGENT.md section 4). | done | M0 | ACC-M0-001, ACC-M0-003 |
| REQ-NF-008 | A clean checkout runs: `uv sync` → `make lint` / `make test`; `make demo` places a real call. | done | M0 | ACC-M0-002, ACC-M0-009, ACC-M4-002 |
| REQ-NF-009 | No performance or capacity claims: no call rate, latency or capacity target is defined for the POC. | done | M0 | ACC-M0-011 |
| REQ-NF-010 | Console uses no third-party front-end libraries and no build step. | done | M0 | ACC-M3-001 |
| REQ-NF-011 | The verdict is a **pure function**: no sockets, no global state and no clock access inside the engine (time is injected), unit-testable without a network (AGENT.md section 12, REQ-NF-004 precedent). | done | P8 | ACC-P8-004 |
| REQ-NF-012 | Cross-call anti-fraud state is **in memory**; a restart loses it. This is a registered POC gap, closed in P11 by the pluggable state store (D9). | done | P8 | ACC-P8-004 |
| REQ-NF-013 | No media is played. A real UAC that does not declare `sip.608` would require a media announcement; this is a registered POC gap, not a hidden defect (D5, ADR-0006). | done | P8 | ACC-P8-003 |
| REQ-NF-014 | Configuration is through environment variables only, declared in `.env.example`; **no new third-party dependency** is added (AGENT.md section 8). | done | P8 | ACC-P8-001 |
| REQ-NF-015 | The `608` reject path is verified **by running sippy**, not assumed (AGENT.md section 6). | done | P8 | ACC-P8-006 |
| REQ-NF-016 | Cross-AS Call-ID correlation is **not solved**: two B2BUAs in series produce two different Call-IDs, because a B2BUA regenerates the dialog `Call-ID` for its second leg (`Call-ID` is not in the pass-through set), so a chained call appears as two independent per-instance traces. This is a registered POC gap, made visible rather than hidden (D6, plan section 3 P9 known issue). | done | P9 | ACC-P9-003 |
| REQ-NF-017 | The chained topology is demonstrated by a **first-class, documented run command** runnable from a clean checkout, mirroring `make demo` / `make demo-fraud`. Chaining reuses the existing peer/listen knobs, so it adds **no new environment variable and no new port** (D6, `AGENT.md` section 8). | done | P9 | ACC-P9-004 |
| REQ-NF-018 | The friction the chained demo surfaces — what in the shared skeleton turned out to be number-translation specific — is **recorded**, as the primary input to P10 (plan section 3 P9 deliberate output). | done | P9 | ACC-P9-005 |
| REQ-NF-019 | The new repository is a **library, not a running service**, so it follows the **library documentation standard** of D8 — an **API reference**, an **integration guide** and a **compatibility matrix** — and does **not** copy this repository's application document set (the ~24 documents of `docs/`, including the operations set `deployment` / `runbook` / `troubleshooting`, which does not apply to a library). It is **not** a uv workspace monorepo (D8). | done | P10 | ACC-P10-005 |
| REQ-NF-020 | The two pluggable dimensions P11 verifies (**transport**: UDP/TLS; **state store**: in-memory/Redis) and P11's **capacity harness** (D10) are **enabled by, but not built in, P10**: the extraction leaves those boundaries pluggable and adds no second transport, no external store and no load harness. The in-memory cross-call state (`REQ-NF-012`) remains the only implementation until P11 (D9). | done | P10 | ACC-P10-006 |
| REQ-NF-021 | The new repository carries **its own test suite and its own gate** (`ruff` format and lint, `mypy`, `pytest`), so a change to the library is verifiable **where the library lives** rather than only through this repository's suite. Its suite covers the pure helpers and the sippy adapter boundary, plus the library-level independence assertion of `REQ-F-030`. The three layers of `AGENT.md` §11 are the **application's** layers (AS and mock S-SBC on UDP, a full call) and do not transfer to a library, which is why this row states a library-shaped suite instead of restating them (D8: the new repository follows the library standard, not the application standard). | done | P10 | ACC-P10-008 |

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
  records that no iFC emulation is needed in the mock — pointing AS-1's next hop at AS-2's
  listen address is a peer/catalogue setting — and the anti-fraud AS relays an allowed call
  to its single configured next hop (`FRAUD_SBC_PEER_*`), so the chain is wired from the
  existing knobs and the routing catalogue. **Structural change (`REQ-NF-017`).** P9
  introduces a **new run command** — a chained-demo entry point mirroring `make demo` /
  `make demo-fraud`. Under `AGENT.md` section 13 a changed run command is a structural
  change, so the implementation commit must update `AGENT.md` section 10, `README.md` and
  `docs/README.md` in the same commit. The chained topology needs **no new environment
  variable and no new port**: the two AS listen ports (`5060` / `5062`) already differ
  precisely so both instances can run on one host (plan section 6). **Known issue
  (`REQ-NF-016`, `REQ-F-028`).** Two B2BUAs in series mean two Call-IDs: each AS terminates
  the incoming INVITE and originates its own second leg, and `Call-ID` is regenerated rather
  than passed through (`src/as_app/sip_adapter.py`, `PASSTHROUGH_HEADERS`), so cross-AS
  correlation is unsolved and is registered as a POC gap rather than assumed away.
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
