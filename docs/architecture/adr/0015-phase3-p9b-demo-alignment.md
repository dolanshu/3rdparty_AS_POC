# ADR-0015: Phase 3 live-load demo aligned with P9b chained topology (P14)

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** `docs/phase3-p9b-alignment-plan.md` · ADR-0014 · `docs/phase3-plan.md` ·
  REQ-F-051…REQ-F-055

## Context

Phase 3 (v1.0.0) shipped an interactive load generator and enhanced console. P9b (ADR-0014)
reworked the chained topology to iFC orchestration. The Phase 3 demo (`scripts/phase3-demo.sh
full`) still wired both AS instances directly to core.

## Decision

1. **Multi-process AS + `ims_mock.external_runtime`** — orchestrator/S-SBC/P-CSCF/UAS run in
   one process; anti-fraud and translation AS stay separate processes (REQ-NF-028).
2. **Generator `topology` flag** — `simple`, `fraud`, `chained`; chained mode adds `Route` to
   S-SBC return and targets AS-1 ingress (REQ-F-052).
3. **Console mode-aware UI** — topology badge, chained SVG, dual `/ws/p12/events` when fraud
   API is configured (REQ-F-053, REQ-F-054).
4. **Lazy orchestrator sessions** — external load generator does not call `begin_session`;
   orchestrator creates AS-1-await state on first return-leg `Call-ID`.
5. **`capacity_probe.py` remains out of scope** for P14.

## Consequences

- `scripts/phase3-demo.sh full` starts `python -m ims_mock.external_runtime`.
- Console gains `--fraud-api-url`; version bump to 1.1.0.
- `as_platform` unchanged (REQ-NF-027).
