# ADR-0016: Call Trace sequence view and phased SIP payload API

- **Status:** accepted; Phase A **done** (2026-09-24); Phase B **done** (2026-09-24)
- **Date:** 2026-09-24
- **Related:** `docs/features/call-trace-message-flow/` ·
  `docs/requirements/functional-and-nonfunctional.md` (REQ-F-056, REQ-F-057) ·
  ADR-0011 (vendored front-end policy) · ADR-0002 (console separate process) ·
  `AGENT.md` §4.4 · `docs/architecture/hld.md` (signalling sequence)

## Context

M3 delivered a **Call Trace** centre view: live message flow, direction colours,
Call-ID filter, payload viewer (`CHANGELOG.md` 0.4.0). P13 moved live traffic to
the Dashboard bottom panel (P12 WebSocket) and left `#vw-call-trace` as a
placeholder redirect (`docs/phase3-gap-audit.md` §7). That satisfies ACC-P13-008
(nav entry exists) but not the original **REQ-F-012** narrative ("live message
flow" as a dedicated trace surface).

The HLD documents the allow-path as a three-party sequence (mock S-SBC forward →
AS → mock S-SBC return). The data to render it already exists: `TraceRecorder`
records ordered `TraceEvent` rows (`direction`, `method`, `attributes.leg`) and
exposes them on `GET /api/v1/traces/{call_id}`. The console no longer calls that
endpoint.

A second requirement emerged: clicking a message should show **verbatim SIP**.
That lives today only in test tooling (`SipMessageRecorder` on the AS stack in
fixtures), not in the production AS internal API.

## Decision

**Deliver Call Trace message flow in two phases on one UI shell.**

### Phase A (console only)

1. **Selection model:** clicking a row in Live Call Trace sets `selectedCallId`
   (+ `source` for dual-AS routing).
2. **Data:** fetch `GET /api/v1/traces/{call_id}` from the correct AS base URL.
3. **Rendering:** **custom inline SVG** sequence diagram (three lifelines: FWD,
   AS, RET) — same technique as the topology panel. **No Mermaid**, no new
   vendored library (ADR-0011).
4. **Detail modal:** show structured `TraceEvent` fields. **Do not synthesize**
   fake SIP wire format when no capture exists.
5. **Replace** the placeholder copy in `#vw-call-trace`.

### Phase B (AS + console extension)

1. Wire **`SipMessageRecorder`** (or equivalent dual-write) on the AS process and
   expose `GET /api/v1/traces/{call_id}/messages` returning trunk + outbound
   Call-ID messages (`messages_for_any`).
2. **Reuse** Phase A SVG and modal; add SIP `<pre>` when a message matches the
   clicked event (heuristic match — see consequences).
3. Register memory/privacy gap in `docs/production-gaps.md`.

### Explicit non-decisions

- Do **not** remove P12 bottom live trace or replace it with `WS /ws/events`.
- Do **not** solve cross-AS Call-ID correlation (ADR-0014 gap remains visible).

## Consequences

### Good

- Phase A is shippable without `as_platform` or AS code changes (REQ-NF-027 friendly).
- SVG ladder aligns with HLD diagram and existing console craft constraints.
- Phase B extends modal + fetch only — no second diagram implementation.
- Restores operator-facing **REQ-F-012** value without breaking P13 Dashboard layout.

### Bad / accepted cost

- **Incomplete ladder:** `TraceRecorder` may omit some trunk-leg events on fast
  teardown; diagram shows **recorded** events only (not idealised RFC ladder).
- **Phase B matching:** event index ↔ SIP message may be imperfect when multiple
  messages share method/direction; modal falls back to event-only + nearest message.
- **Memory:** verbatim SIP store is bounded but sensitive; demo-only default, noted
  in SECURITY.md / production-gaps.
- **Dual AS:** one trace view per AS instance; chained demos may require selecting
  rows from different sources separately.

## Alternatives considered

### Option A — Vendored Mermaid.js

Render HLD-style diagrams from Mermaid source strings. **Rejected:** requires new
ADR + bundle under ADR-0011; heavier than needed for fixed three-lifeline layout.

### Option B — Reconnect `WS /ws/events` only

Poll TraceRecorder over WebSocket for the Call Trace page. **Rejected as sole
source:** REST on select is simpler for detail view; P12 WS remains for live list.

### Option C — Big-bang Phase B before any UI

Ship messages API first, then UI. **Rejected:** delays visible value; Phase A proves
UX and mapping before payload storage work.

## Implementation pointers

- Feature plan: `docs/features/call-trace-message-flow/plan.md`
- Design: `docs/features/call-trace-message-flow/design.md`
- Delivery skill: `.cursor/skills/feature-delivery/SKILL.md`
