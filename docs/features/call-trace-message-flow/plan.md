# Feature plan: Call Trace message flow (Phase A → B)

**Feature slug:** `call-trace-message-flow`  
**Status:** Phase A + B **Done** (2026-09-24) — Stages 0–11 complete  
**Branch:** `phase3` (or maintainer-named feature branch)  
**Date:** 2026-09-24  

---

## 1. Goal

Restore the **Call Trace** nav view as a real per-call **message flow** surface:

| Phase | Delivers | Data source |
| --- | --- | --- |
| **A** | Bottom panel row select → Call Trace page → **SVG sequence diagram** (FWD / AS / RET) + **event detail modal** | `GET /api/v1/traces/{call_id}` (`TraceRecorder`) |
| **B** | Same UI; arrow click also shows **verbatim SIP** when available | `GET /api/v1/traces/{call_id}/messages` (new; `SipMessageRecorder` in AS) |

Phase A intentionally builds the **seams** Phase B extends (see `design.md` §6).

Aligns with `docs/architecture/hld.md` sequence (lines 71–91), `AGENT.md` §4.4 centre-panel message flow, and closes `docs/phase3-gap-audit.md` Call Trace placeholder gap.

---

## 2. Traceability (draft IDs)

| ID | Summary |
| --- | --- |
| REQ-F-056 | Phase A — sequence view + event modal from TraceRecorder REST |
| REQ-F-057 | Phase B — verbatim SIP popup from AS message store |
| REQ-NF-031 | Phase B — bounded in-memory SIP capture; no new published benchmark |
| ADR-0016 | SVG ladder + REST trace + phased message API |
| ACC-P15-001 | Phase A acceptance |
| ACC-P15-002 | Phase B acceptance |

Full text: `docs/requirements/functional-and-nonfunctional.md`, `docs/acceptance/criteria.md`, `docs/architecture/adr/0016-call-trace-sequence-view.md`.

---

## 3. Stage workflow (subagent per stage)

**Orchestrator:** parent agent only — dispatch, collect verdict, update this table.  
**Skill:** `.cursor/skills/feature-delivery/SKILL.md`

| Stage | Work | Executor subagent | Review subagent | Exit criterion | Status |
| --- | --- | --- | --- | --- | --- |
| 0 | Plan on disk | parent | — | This file + skill exist | **Done** |
| 1 | Requirements + ACC draft | `generalPurpose` | `generalPurpose` | REQ/ACC rows merged | **Done** |
| 2 | ADR-0016 + production-gaps | `generalPurpose` | `generalPurpose` | ADR accepted shape | **Done** |
| 3 | `design.md` + LLD pointer | `generalPurpose` | `generalPurpose` | Seams documented | **Done** |
| 4 | `testing-plan.md` + testing doc deltas | `generalPurpose` | `generalPurpose` | Tests named | **Done** |
| 5 | Phase A coding | `generalPurpose` | — | `src/console/main.py` | **Done** |
| 6 | Phase A tests | `generalPurpose` | — | pytest green | **Done** |
| 7 | Review gate A | — | `generalPurpose` | APPROVE | **Done** (tests pass) |
| 8 | Phase B coding | `generalPurpose` | — | Messages API + modal | **Done** |
| 9 | Phase B tests | `generalPurpose` | — | pytest green | **Done** |
| 10 | Review gate B | — | `generalPurpose` | APPROVE | **Done** |
| 11 | Acceptance closure | `generalPurpose` | — | criteria/report | **Done** |

Store review outputs under `docs/features/call-trace-message-flow/reviews/stage-NN-*.md` (optional but recommended).

---

## 4. Subagent prompts (copy-paste)

### Stage 1 — Requirements

```
Full Repository Path: /home/shudong/project/3rdparty_AS_POC
Feature slug: call-trace-message-flow
Stage: 1 — Requirements

Read: docs/features/call-trace-message-flow/plan.md, AGENT.md §13, docs/requirements/functional-and-nonfunctional.md (REQ-F-012 context)

Deliver:
- Add REQ-F-056, REQ-F-057, REQ-NF-031 to docs/requirements/functional-and-nonfunctional.md
- Add ACC-P15-001, ACC-P15-002 draft to docs/acceptance/criteria.md (new § Phase 3 — P15 Call Trace message flow)
- Note REQ-F-012 gap: placeholder Call Trace view vs SRS wording

Do NOT: ADR, code, tests
Completion: IDs consistent across plan, requirements, acceptance
```

### Stage 2 — ADR

```
Stage: 2 — ADR
Read: approved Stage 1 artifacts, docs/features/call-trace-message-flow/plan.md, ADR-0011 (vendoring precedent)

Deliver:
- docs/architecture/adr/0016-call-trace-sequence-view.md
- docs/production-gaps.md row for Phase B in-memory SIP store
- Update docs/README.md ADR index (0016 line)

Decision must cover: custom SVG (no Mermaid), REST TraceRecorder for Phase A, optional messages API Phase B, dual-AS URL routing by event source
```

### Stage 3 — Design

```
Stage: 3 — Design
Read: ADR-0016, docs/architecture/hld.md §key flow (sequence diagram), src/console/main.py (trace panel, vw-call-trace)

Deliver: docs/features/call-trace-message-flow/design.md
Include: UI flow, event→arrow mapping, modal API showDetail({event, sip}), DOM ids, chained/fraud AS_URL selection, empty/error states
Add ≤20 lines pointer in docs/architecture/lld.md §console or new subsection
```

### Stage 4 — Testing plan

```
Stage: 4 — Testing plan
Read: design.md, docs/testing/integration-plan.md, e2e-playwright-plan.md

Deliver: docs/features/call-trace-message-flow/testing-plan.md
Update: unit-plan (JS mapping pure tests if any), integration-plan, e2e-playwright-plan with new test names and REQ/ACC mapping
```

### Stage 5 — Phase A coding

```
Stage: 5 — Phase A coding
Read: design.md, ADR-0016. Do NOT implement Phase B API.

Deliver:
- src/console/main.py: selectedCallId, row click, fetch trace, renderSequenceSvg, showDetail modal (event only), replace vw-call-trace placeholder
- Minimal CSS inline (match existing console)

Completion: manual smoke — select call id → Call Trace shows ≥1 arrow for completed translation call
```

### Stage 6 — Phase A tests

```
Stage: 6 — Phase A tests
Deliver tests per testing-plan.md; run:
  uv run pytest tests/integration/test_console.py tests/e2e/test_console_dashboard.py -v -k "call_trace or sequence"
Completion: all new tests pass
```

### Stage 7 — Review gate A

```
Stage: 7 — Review
Diff: uncommitted changes for Phase A only
Review: design.md compliance, REQ-F-056, no Phase B scope, ADR-0011 (no new vendored libs)
Verdict: APPROVE | REVISE
```

### Stages 8–10 — Phase B

Same pattern; executor reads design.md §6 and ADR-0016 Phase B; backend in `src/as_app/internal_api.py` (+ anti_fraud mirror if required); review includes SECURITY.md payload exposure.

---

## 5. Non-goals

- Vendoring Mermaid or a second front-end library (ADR-0011)
- Replacing P12 bottom live trace with TraceRecorder polling (keep both: P12 feed + REST detail on select)
- Cross-AS Call-ID correlation (ADR-0014 gap stays visible)
- Publishing SIP captures in acceptance evidence repos (SECURITY.md)

---

## 6. Dependencies

- Existing `GET /api/v1/traces/{call_id}` on translation AS (and fraud AS when `--fraud-api-url` set)
- `TraceEvent.direction`, `.method`, `.attributes.leg` from `as_platform` (no library change in Phase A)
- Phase B may touch `as_app` only (REQ-NF-027) unless maintainer approves `as_platform` API extension

---

## 7. Risks

| Risk | Mitigation |
| --- | --- |
| Trace incomplete (missing trunk BYE) | Document in design; diagram shows recorded events only |
| Event↔message 1:1 alignment hard in B | Modal shows best-match message by order/timestamp; diagram unchanged |
| E2E flakiness on generator load | Integration test with `trunk_pair`; E2E selects stable call from `#tlist` |

---

## 8. Stage log

| Date | Stage | Result | Notes |
| --- | --- | --- | --- |
| 2026-09-24 | 0 | Done | Plan + skill committed |
| 2026-09-24 | 5–7 | Done | Phase A console + tests; review APPROVE |
| 2026-09-24 | 8–9 | Done | Messages API + modal SIP; integration + e2e green |
| 2026-09-24 | 10–11 | Done | Review gate B APPROVE; ACC-P15-001/002 closed |
