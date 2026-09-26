# ADR-0012: Load generator boundary — external SIP UAC, not library callback

- **Status:** Accepted
- **Date:** 2026-09-21
- **Deciders:** project maintainer
- **Related:** `docs/phase3-plan.md` (D6, D7, P12 Stage 2) ·
  `docs/post-phase2-directions.md` Part B D6 ·
  `docs/requirements/functional-and-nonfunctional.md` (REQ-F-038, REQ-NF-027, REQ-NF-029) ·
  ADR-0010 (P11 capacity harness — callback model) ·
  `tools/capacity_probe.py` (P9.5, P11's probe predecessor) ·
  `tools/chained_as_probe.py` (chained demo probe)

## Context

Phase 2 left two load-testing artefacts that are the direct antecedents of P12's load
generator:

- **P9.5 capacity probe** (`tools/capacity_probe.py`) — a Python script that drives the
  AS through sippy's callback interface. It imports `as_platform`, creates AS instances,
  calls `BaseAsStack.start()` in-process, and sends INVITEs via sippy's `UacStateIdle`.
  All AS instances and the mock S-CSCF run in **one Python interpreter**. P9.5 measured
  that the shared `ED2` event-loop gap grows from 0.03 s to 0.12 s at 64 concurrent calls
  — the bottleneck is a single process's sippy loop handling everything at once.

- **P11 capacity harness** (`as_platform` library) — the library-level formalisation of
  the same callback model. Any AS application that consumes `as_platform` can invoke
  the harness to drive its stack at increasing offered concurrency levels. Still
  **in-process**: the harness drives AS instances through the library's callback API.

P12's load generator is different. It must (a) demonstrate the AS handles N concurrent
calls running as **independent processes** (each AS has its own `ED2` loop — per-AS
concurrency, not cross-AS), (b) run indefinitely as an interactive tool with REST API
controls, and (c) prove `REQ-F-043` (concurrent `CallController` isolation under load).

Three design candidates are on the table:

### Option A — In-process callback (P9.5 / P11 model, extend it)

The generator creates AS instances in the same Python interpreter and drives them through
sippy callbacks. Same architecture as P9.5 and P11.

### Option B — External SIP UAC (P12 chosen)

The generator is a standalone process that talks to AS processes via **real SIP**
(UDP INVITEs to the configured SIP listen port). Each AS runs as its own process with
its own sippy `ED2` loop. The generator's mock S-CSCF UAC sends real SIP messages and
receives real SIP responses.

### Option C — Networked callback (hypothetical)

Somehow serialize the P11 harness's callback interface over a socket and have the
generator invoke it from outside. Not realistically implementable given that sippy's
callbacks are not designed for cross-process invocation.

## Decision

**Option B — External SIP UAC.**

The generator (`tools/call_load_generator.py`) is a standalone Python process that:

1. Creates a mock S-CSCF UAC (reusing `tools/chained_as_probe.py`'s UAC pattern but
   extended with duration-class-controlled far-end behavior).
2. Sends SIP INVITEs to the AS's configured SIP listen port.
3. Tracks each call's dialog state machine from the outside (sends BYE at the configured
   duration class, or lets the AS tear down on timeout).
4. Observes AS behavior via the AS's internal API WebSocket feed (per-call events).
5. Is controlled via its own REST API (`/load/start`, `/load/stop`, `/load/config`,
   `/load/status`) and exposes its own WebSocket event feed.

The generator does **not** import `as_platform`, `src/as_app`, or
`src/anti_fraud_as` (REQ-NF-029). It talks to AS processes only via SIP
(INVITE/200/BYE/CANCEL/608) and observes only via the event stream.

## Consequences

### What we gain

- **Per-AS concurrency validation.** Each AS process has its own `ED2` loop.
  P9.5's measured bottleneck (shared loop gap at 64 concurrent calls across all
  instances in one interpreter) does not apply — the bottleneck is per-AS and
  much less severe at the 10–20 concurrent-call level P12 targets.
- **Generator is a SIP-speaking entity.** Any SIP-speaking AS implementation
  (not just this repository's `as_platform`-based ones) can be driven by the
  generator. It is a load tool, not a platform-bound callback.
- **Boundary clarity.** The generator does not need to know about AS internals
  (`CallController`, `BaseAsStack`, `PolicyDecision`). It only knows SIP and the
  event-stream JSON schema. The AS does not need to know about the generator
  (REQ-NF-027 — no `as_platform` changes for P12).
- **Interactive control is natural.** REST API on the generator process is
  straightforward — FastAPI on its own port, separate from the AS's internal API.
  No in-process threading complications.

### What we lose

- **P11 harness reuse.** P11's callback-based harness cannot be extended to do
  what P12 needs because P12 runs AS instances in **separate processes**. P11's
  harness is still valid for its stated purpose (library-level verification), but
  P12 cannot build on it. P11 harness and P12 generator coexist as two separate
  capabilities.
- **One more process to manage.** `make demo` does not start the generator
  (REQ-NF-029 — generator is an **additional** process). A reviewer running the
  full P12 interactive demo starts: (1) AS processes, (2) generator process,
  (3) console. That's three processes — one more than Phase 2's two. This is
  an accepted consequence; the console's control panel (P13) will make this
  transparent to the reviewer.

### Key design rule

The generator **knows call types and duration classes, but not AS internals**.
It sends SIP INVITEs with caller/called number combinations that the AS's rules and
anti-fraud configuration will route into the 10 call types (T1–T6, F1–F4). It does
not assert "this call will be T1" — it asserts "I sent an INVITE with these numbers"
and observes the AS's decision via the event stream. If the AS configuration changes,
the generator's behavior changes too, without code modification.
