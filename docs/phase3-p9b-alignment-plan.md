# Phase 3 × P9b alignment plan — chained live-load demo (P14)

- **Status:** implemented (P14, 2026-09-23)
- **Date:** 2026-09-23
- **Owner:** project maintainer
- **Related:** `docs/phase3-plan.md` (P12/P13, v1.0.0) · `docs/chained-topology-plan.md`
  (P9b, implemented) · ADR-0014 · `docs/architecture/hld.md` §9 (chained topology) ·
  §12 (Call Load) · `scripts/phase3-demo.sh` · REQ-F-040 · REQ-NF-027/029

---

## 1. Purpose and scope

Phase 3 (P12 Call Load + P13 Enhanced Console) shipped at **v1.0.0** with genuine
**within-AS** concurrent isolation and a live operations dashboard. P9b (2026-09-23)
reworked the **chained topology** to the iFC-orchestrated model (`src/ims_mock/`,
ADR-0014). The two bodies of work are **not yet integrated** in the interactive demo path.

**This document is the single detailed source for closing that gap.** It aligns:

1. **`scripts/phase3-demo.sh`** — `full` mode must run the **P9b chain**, not two AS
   instances each wired directly to their own mock return side.
2. **`tools/call_load_generator.py`** — REQ-F-040's **chained** target must be selectable
   at runtime and reflected in `/load/status`.
3. **`src/console/main.py`** — the Dashboard topology, event feeds and controls must
   **honestly reflect** which mode is running (simple / fraud-only / chained).

**What this plan covers**

- Strategic decisions, target architecture, console UI specification, work sequence,
  file checklist, REQ/ACC map, risks.

**What this plan does not cover**

- `tools/capacity_probe.py` trunk-to-trunk wiring — **explicitly deferred** (same class
  of fix as P9b-5 note; tracked separately, not P14 scope).
- Changes to `../as_platform` (REQ-NF-027 unchanged).
- Changes to the two AS binaries beyond existing P12 `_emit_p12` hooks.
- Full iFC/ISC production fidelity (same POC simplification as P9b §8).

**Handover rule.** A conversation implementing P14 reads `AGENT.md`, `docs/README.md`,
**this document**, `docs/chained-topology-plan.md` §3 (sequences), `docs/phase3-plan.md`
§2 D6–D7, then starts. Conversation context is not a handover artefact (`AGENT.md` §15).

---

## 2. Problem statement (current gaps)

| Area | Current behaviour | Required behaviour |
| --- | --- | --- |
| `phase3-demo.sh full` | Anti-fraud AS and translation AS **each peer to a mock return side**; generator INVITEs anti-fraud only | Generator → **subscriber ingress** → iFC chain **AS-1 → AS-2 → terminating UAS** (ADR-0014) |
| `call_load_generator.py` | Only `--as-port`; no topology flag | `--topology simple\|fraud\|chained` + ingress port(s); status exposes active topology |
| Console SVG | Fixed 4-node diagram `S-SBC → Anti-fraud → Translation → S-SBC ret`; **always drawn regardless of the running AS**; 3 links share one colour/width | Mode-aware diagram; **inactive nodes dimmed** in simple mode; **chained layout** shows iFC hop; per-hop link styling where data exists |
| Console WebSockets | **One** AS event stream (`--as-api-url` → translation only) | Chained/full mode: **both** AS instances' `/ws/p12/events` merged into trace + charts |
| Console health | Single AS health strip | Full/chained: **dual** instance health (fraud + translation) |
| Integration tests | `chained_pair_factory` uses P9b `ims_mock` (in-process AS) | Demo uses **multi-process AS** + external `ims_mock` wiring — needs new runtime + smoke test |
| REQ-F-040 evidence | Call types validated in unit tests; chained mode not in interactive demo | Demo + acceptance prove chained load at reviewer-chosen concurrency |

P12/P13 acceptance (`ACC-P12-*`, `ACC-P13-*`) remains valid for what was delivered at v1.0.0.
P14 adds **new** acceptance rows; it does not retroactively fail v1.0.0.

---

## 3. Strategic decisions

### D1 — Demo AS instances stay separate processes

**Decision.** Phase 3's narrative — each AS owns its own sippy `ED2` loop (`REQ-NF-028`) —
is preserved. P14 does **not** fold AS processes into `ChainedImsStack` for the demo.

**Rationale.** `ChainedImsStack` (tests/probes) runs both AS in one interpreter for
determinism. The live-load dashboard demo must show **real multi-process** behaviour.

**Consequence.** P14 introduces an **`ims_mock` external wiring** layer: orchestrator +
S-SBC + P-CSCF + terminating UAS in one (or two) processes, with `chain_config` pointing
at **external** AS-1/AS-2 UDP ports started by the supervisor.

### D2 — Three topology modes (matches demo + REQ-F-040)

| Mode | Generator ingress | AS processes | Console topology |
| --- | --- | --- | --- |
| `simple` | Translation AS SIP port | Translation only + terminating UAS (or S-SBC return mock) | 3-hop: S-SBC → Translation → S-SBC ret |
| `fraud` | Anti-fraud AS SIP port | Fraud only + S-SBC return mock | 3-hop: S-SBC → Anti-fraud → S-SBC ret |
| `chained` | **Orchestrator subscriber / S-SBC forward port** | Fraud + Translation + ims_mock runtime | 5-hop: S-SBC → AS-1 → iFC → AS-2 → UAS |

**Rationale.** REQ-F-040 already names all three targets; P13 shipped a chained-shaped SVG
without enforcing it on the wire.

**Consequence.** Generator REST `PUT /load/config` may include `topology` (immutable while
pool running, or applied on next start — pick **on next start** to avoid mid-flight
topology flips; document in P14-0).

### D3 — Console is mode-aware, not mode-agnostic

**Decision.** The Dashboard reads `topology` from `GET /load/status` (and
`pool_status_update`) and switches layout + WS connections accordingly.

**Rationale.** A chained diagram while running `simple` mode mis-teaches reviewers; dimming
inactive nodes is insufficient without a visible **mode badge**.

**Consequence.** P14 touches `src/console/main.py` only (P13 boundary respected); no AS
source changes beyond what P12 already added.

### D4 — Event merge at the browser, not a new proxy service

**Decision.** Console opens **one or two** WebSockets to AS internal APIs and merges events
in `onCallEvent()` (keyed by `call_id` + `source`). No new merge service in the generator.

**Rationale.** Keeps process count stable; `source` field already exists on P12 events.

**Consequence.** Console CLI gains `--fraud-api-url` (optional). When omitted, behaviour
is identical to v1.0.0 (translation API only).

### D5 — Per-hop link metrics: generator-led, best-effort

**Decision.** Phase 1 of P14 styles SVG links from **aggregate** counters (existing
`pool_status_update.active_calls` + per-AS event counts). Optional stretch (P14-4b): generator
emits `hop_status_update` with `{hop: "as1_trunk", active: N}` if instrumentation is cheap.

**Rationale.** REQ-F-048 asked for hop-proportional thickness; honest chained mode needs at
least **as1_trunk / ifc / as2_trunk** distinction. Full per-hop counts may require generator
to track orchestrator session state — defer if costly.

**Minimum bar.** In `chained` mode, **five links** (`l1`…`l5`) animate together from
`active_calls`; reject colour propagates from fraud events; completed colour from translation
events.

### D6 — `as_platform` and `make demo` unchanged

**Decision.** P14 does not modify `../as_platform`. `make demo` / `make demo-chained` stay
self-contained; only `scripts/phase3-demo.sh` and P14 tests use the new stack supervisor.

**Consequence.** Version bump: **1.1.0** (additive demo alignment, not a new major capability).

### D7 — `capacity_probe.py` out of scope

**Decision.** P14 explicitly excludes `tools/capacity_probe.py`. A follow-on item (P14.5 or
P9b-5 remainder) may align it later.

---

## 4. Target architecture

### 4.1 Process diagram (`phase3-demo.sh full` + `topology=chained`)

```
┌─────────────┐  SIP INVITE   ┌──────────────────────────────────────────┐
│ load        │ ────────────► │ ims_mock runtime (supervisor process)       │
│ generator   │               │  • S-SBC forward/return                     │
│ :8765       │               │  • ChainedOrchestrator (iFC #1 / #2)        │
└──────┬──────┘               │  • P-CSCF relay + terminating UAS           │
       │ WS /pool             └───────┬──────────────────────┬───────────────┘
       │                            │ trunk INVITEs        │ trunk INVITEs
       ▼                            ▼                      ▼
┌─────────────┐              ┌──────────────┐       ┌──────────────┐
│ console     │◄── WS ──────│ anti-fraud   │       │ translation  │
│ :8081       │   p12/events │ AS process   │       │ AS process   │
│             │◄── WS ──────│ :5062        │       │ :5060        │
└─────────────┘              └──────────────┘       └──────────────┘
       ▲
       └── fraud API :8082 + translation API :8080
```

### 4.2 Sequence (one allow call, chained mode)

Same as `docs/chained-topology-plan.md` §3.1 allow path. Generator plays **subscriber UAC**
role (initial INVITE into orchestrator ingress, not direct AS-1 port).

### 4.3 Wiring matrix (demo env)

| Knob | Chained `full` value |
| --- | --- |
| `FRAUD_SBC_PEER_*` | S-SBC **return** port (orchestrator), **not** translation AS |
| `SBC_PEER_*` (translation) | Same return port |
| Generator `--as-port` / `--ingress-port` | S-SBC **forward** port (subscriber ingress) |
| `chain_config` | `[("anti-fraud", 127.0.0.1, AS_FRAUD_SIP), ("translation", 127.0.0.1, AS_TRANS_SIP)]` |
| Rules rewrite | `rewrite_next_hop_ports` → return port (same as `chained_helpers`) |

### 4.4 Interface additions

| Interface | Change |
| --- | --- |
| Generator `GET /load/status` | Add `topology: "simple" \| "fraud" \| "chained"`, `ingress_port: int` |
| Generator `PUT /load/config` | Add optional `topology` (validated; default `simple`) |
| Console page | `__FRAUD_API_URL__` token (optional empty → hide fraud panel) |
| Console JS | `topology` from load status → `setTopologyMode(mode)` |

---

## 5. Console UI specification

P13 shipped a single Dashboard layout. P14 **extends** it without removing legacy views
(ACC-P13-008 preserved).

### 5.1 Mode badge and legend

| Element | ID | Behaviour |
| --- | --- | --- |
| Topology mode badge | `#topoMode` | Text: `Simple` / `Fraud only` / `Chained (iFC)` from generator status |
| Binding constraint | (existing) | Unchanged — still shows 池子上限 / Call Rate 限速 |
| ICID hint (chained only) | `#topoHint` | One line: "Cross-AS correlation: ICID in P-Charging-Vector (not Call-ID)" — links production gap row |

### 5.2 SVG layouts

**Layout A — `simple` / `fraud`** (reuse current geometry, rename nodes):

| Mode | Nodes shown | Dimmed |
| --- | --- | --- |
| `simple` | S-SBC → Translation → S-SBC ret | Anti-fraud node + iFC node hidden or 30% opacity |
| `fraud` | S-SBC → Anti-fraud → S-SBC ret | Translation node hidden or dimmed |

**Layout B — `chained`** (new SVG group `#topoChained`, hidden when not chained):

```
[Gen] ─l1─ [S-SBC] ─l2─ [Anti-fraud] ─l3─ [iFC] ─l4─ [Translation] ─l5─ [UAS]
```

- **iFC** node = S-CSCF orchestrator (single labelled box; no separate P-CSCF box on SVG —
  tooltip text mentions P-CSCF → UAS internally).
- Node boxes use existing CSS variables; inactive-mode nodes use `opacity: 0.25`.

**Link styling** (`updateTopology(mode)`):

| Link | Driven by (minimum) |
| --- | --- |
| l1 | `active_calls` (generator) |
| l2 | fraud `call_started` − fraud terminal events |
| l3 | fraud allow events (proxy for iFC #2 trigger) |
| l4 | translation `call_started` |
| l5 | translation `call_ended` completed |

Colour precedence unchanged: red if `rejected_608` > 0 on fraud stream; orange if timeout;
green if active/completed.

### 5.3 Dual AS health strip

When `__FRAUD_API_URL__` is non-empty:

| Element | Source |
| --- | --- |
| `#fraudDot`, `#fraudSt`, `#fraudVer` | `GET {fraud}/healthz` every 3s |
| `#transDot`, `#transSt`, … | `GET {trans}/healthz` (existing strip renamed) |

When fraud URL empty, hide fraud strip (v1.0.0 compatible).

### 5.4 WebSocket connections

| Mode | Connections |
| --- | --- |
| `simple` | `ws://{trans}/ws/p12/events` only |
| `fraud` | `ws://{fraud}/ws/p12/events` only (translation WS not opened) |
| `chained` | **Both** fraud + translation WS; `onCallEvent` tags `source` (`as_fraud` / `as_translation`) |

Trace list: optional filter chips `All | Fraud | Translation` (P14-4c stretch; minimum:
show `source` column — already present).

### 5.5 Load controls vs topology

| Control | `simple` | `fraud` | `chained` |
| --- | --- | --- | --- |
| T1–T6 toggles | enabled | **disabled** (grey + tooltip) | enabled |
| F1–F4 toggles | **disabled** | enabled | enabled |
| Start | allowed if ≥1 enabled type valid for mode | same | same |

Client-side validation before `PUT /load/config`; server rejects invalid type sets for mode
(HTTP 400).

### 5.6 Chart behaviour (unchanged semantics)

- Line chart, pie chart, gauge: **no formula change**; merged event streams feed same counters.
- In chained mode, `call_started` on **both** AS instances increments `counters.active` once
  per event — **document** that active count is event-oriented (may exceed pool size briefly);
  gauge uses `pool_status_update.active_calls` as authoritative for generator pool.

### 5.7 Integration test updates

| Test file | Change |
| --- | --- |
| `tests/integration/test_console.py` | Assert `#topoMode`, `#topoChained` exist; vendored static unchanged |
| `tests/e2e/test_console_dashboard.py` | Chained layout visible when status mock returns `topology: chained`; dual WS when fraud URL set |

---

## 6. Work sequence

### P14-0 — Requirements and ADR stub

| Deliverable | Action |
| --- | --- |
| `docs/requirements/functional-and-nonfunctional.md` | Add REQ-F-051…055 (see §8); mark `accepted`, milestone P14 |
| `docs/architecture/adr/0015-phase3-p9b-demo-alignment.md` | Record D1–D7 |
| `docs/acceptance/criteria.md` | Add `ACC-P14-001`…`008` skeleton |
| `docs/chained-topology-plan.md` §4 P9b-5 | Mark `phase3-demo.sh` orchestrator row → **superseded by P14** |

**Review gate:** read-only per `docs/phase3-plan.md` §5.2 before code.

### P14-1 — External chained runtime

| Module | Responsibility |
| --- | --- |
| `src/ims_mock/external_runtime.py` (new) | Build orchestrator + S-SBC + P-CSCF + UAS; **no in-process AS**; `start(as1_port, as2_port, …)` |
| `tools/phase3_stack_supervisor.py` (new) | CLI: spawn AS subprocesses + `external_runtime`; print ports JSON for shell script |
| `src/ims_mock/chained_stack.py` | Refactor shared wiring used by tests **and** external runtime (avoid duplication) |

**Unit tests:** external runtime FSM smoke with mocked UDP (no subprocess).

**Exit:** supervisor starts; health script receives ingress + API ports; one manual INVITE completes chain.

### P14-2 — Load generator topology

| File | Action |
| --- | --- |
| `tools/call_load_generator.py` | `--topology`, `--ingress-port` (alias `--as-port` for back compat); status field; config validation |
| `tests/unit/test_generator_api.py` | Topology in status; 400 on invalid type set per mode |
| `tests/integration/test_concurrent_load.py` | Optional: one test via `external_runtime` + subprocess AS (if feasible) |

**Exit:** `uv run python tools/call_load_generator.py --topology chained --ingress-port <P>` starts pool against real chain.

### P14-3 — `scripts/phase3-demo.sh`

| Mode | Processes |
| --- | --- |
| `simple` | translation AS + S-SBC return/terminating + generator + console (unchanged ports) |
| `full` | supervisor chained stack + generator (`--topology chained`) + console (dual API URLs) |

Remove direct `FRAUD_SBC_PEER_PORT=CORE_SIP` peer-to-return-side wiring in `full`.

**Exit:** `./scripts/phase3-demo.sh full` → console shows `Chained (iFC)`; Start → calls traverse both AS.

### P14-4 — Console UI (P13 extension)

| File | Action |
| --- | --- |
| `src/console/main.py` | Mode badge, layout B SVG, `setTopologyMode`, dual WS, dual health, toggle gating |
| `tests/integration/test_console.py` | New assertions per §5.7 |
| `tests/e2e/test_console_dashboard.py` | Topology mode + dual WS cases |

**Exit:** Playwright green; manual demo matches `docs/demo-script.md` §7 update.

### P14-5 — Documentation

| File | Action |
| --- | --- |
| `docs/demo-script.md` §7 | Chained live-load narrative |
| `docs/demo-steps.md` Part 3 | Commands for `full` + topology |
| `docs/architecture/hld.md` §11.1 | Diagram: chained ingress via ims_mock |
| `docs/architecture/lld.md` | New §12.x console topology modes + supervisor |
| `docs/roadmap.md` | P14 status row |
| `docs/README.md` | Index row for this plan |
| `README.md` | One paragraph under Phase 3 demo |
| `CHANGELOG.md` / `VERSION` | 1.1.0 |

### P14-6 — Acceptance

Run `ACC-P14-*`; record evidence in `docs/acceptance/report.md`.

---

## 7. REQ / ACC map (draft)

| ID | Requirement | ACC |
| --- | --- | --- |
| REQ-F-051 | `scripts/phase3-demo.sh full` runs P9b iFC chain with **multi-process** AS instances and generator ingress on orchestrator forward port | ACC-P14-001 |
| REQ-F-052 | Load generator exposes `topology` in config and status; supports `simple`, `fraud`, `chained` per REQ-F-040 completion | ACC-P14-002 |
| REQ-F-053 | Console Dashboard shows **mode badge** and **mode-correct** SVG (simple vs chained); inactive nodes dimmed | ACC-P14-003 |
| REQ-F-054 | Console merges **both** AS `/ws/p12/events` streams in `chained` mode; dual health strip when fraud API configured | ACC-P14-004 |
| REQ-F-055 | Call-type toggles are **topology-aware** (T* disabled in fraud-only, F* disabled in simple) | ACC-P14-005 |
| REQ-NF-031 | P14 does not modify `../as_platform` | ACC-P14-006 |
| REQ-NF-029 | Generator remains external; `make demo` unchanged | ACC-P14-007 |
| (process) | Playwright + integration tests updated; full suite green | ACC-P14-008 |

---

## 8. Files expected to touch (checklist)

**New**

- `docs/architecture/adr/0015-phase3-p9b-demo-alignment.md`
- `src/ims_mock/external_runtime.py`
- `tools/phase3_stack_supervisor.py`
- `tests/unit/test_external_runtime.py` (or under `tests/unit/test_ims_orchestrator.py`)

**Modified**

- `scripts/phase3-demo.sh`
- `tools/call_load_generator.py`
- `src/console/main.py`
- `src/ims_mock/chained_stack.py` (shared wiring extraction — minimal)
- `tests/unit/test_generator_api.py`
- `tests/integration/test_console.py`
- `tests/e2e/test_console_dashboard.py`
- `docs/requirements/functional-and-nonfunctional.md`
- `docs/acceptance/criteria.md`
- `docs/acceptance/report.md` (on completion)
- `docs/demo-script.md`, `docs/demo-steps.md`
- `docs/architecture/hld.md`, `docs/architecture/lld.md`
- `docs/roadmap.md`, `docs/README.md`, `README.md`, `CHANGELOG.md`, `VERSION`

**Explicitly not in P14**

- `tools/capacity_probe.py`
- `../as_platform/**`
- `src/as_app/call_controller.py` / `src/anti_fraud_as/call_controller.py` (unless event shape gap found)

---

## 9. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Subprocess AS + orchestrator port race | Supervisor waits on UDP port bind + `/healthz` before printing ports (same pattern as `phase3-demo.sh wait_port`) |
| Dual WS doubles event rate in charts | Gauge uses generator `active_calls`; pie chart documents event-oriented counting in ADR-0015 |
| WSL2 browser cannot reach WS | Keep `BIND_ADDR=0.0.0.0` + `API_HOST=WSL_IP` pattern from existing script |
| Chained concurrent load flakes | Reuse P9b `chained_pair_factory` patterns; start with concurrency 5 in demo default, 10 in tests |
| SVG clutter on small screens | Chained layout uses smaller font (9px) and horizontal scroll on `#topoPanel` |

---

## 10. Exit barrier (v1.1.0)

1. All `ACC-P14-*` verified with evidence in `docs/acceptance/report.md`
2. `./scripts/phase3-demo.sh full` — reviewer sees **Chained (iFC)** badge, dual AS health green, Start raises active calls through both AS (verifiable in Call Trace `source` column)
3. `./scripts/phase3-demo.sh simple` — v1.0.0-compatible layout (translation only)
4. `make lint` clean; unit + integration + e2e green
5. `CHANGELOG.md` + `VERSION` → `1.1.0`
6. No change to `../as_platform/VERSION`

---

## 11. References

- Implemented P9b chain: `make demo-chained`, `tools/chained_helpers.py`
- Phase 3 baseline: `docs/phase3-plan.md`, `CHANGELOG.md` [1.0.0]
- Console baseline: `src/console/main.py` (`updateTopology`, `onCallEvent`)
- Deferred: `tools/capacity_probe.py` (trunk-to-trunk)
