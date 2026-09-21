# Documentation map

Start with `AGENT.md`. It defines the rules, the standards and the handover protocol.
This page is the index of everything else, grouped by what a reader is trying to do.

Legend: **ready** — exists and is usable · **skeleton** — exists, content pending ·
**planned** — not created yet.

## Architecture review

| Document | Status | What it answers |
| --- | --- | --- |
| `AGENT.md` §1–§5, §15 | ready | Positioning, boundaries, non-goals, delivery standards, roadmap |
| `docs/architecture/hld.md` | ready | System context, deployment view, interface view, quality attributes, key flows — including the second AS instance (§8) |
| `docs/architecture/lld.md` | ready | Modules, data structures, state machines, error codes, process model, log fields — including the anti-fraud AS (§9) |
| `docs/architecture/adr/` | ready | ADR-0001 … ADR-0010: 0001 sippy, 0002 process separation, 0003 UDP only (superseded for the library's pluggable seam by ADR-0010), 0004 YAML rules, 0005 mock strategy, 0006 signalling only, 0007 anti-fraud AS / `608 Rejected`, 0008 chained topology / per-leg `Call-ID`, 0009 platform library extraction / `path` consumption, 0010 P11 TLS + Redis + capacity harness verification |
| `../as_platform/` (the platform library) | ready | The shared skeleton both AS instances build on, in its own repository checked out beside this one and consumed through a `path` source (`editable = true`). Carries its own `ruff` / `mypy` / `pytest` gate and its library-standard documents — API reference, integration guide, compatibility matrix (`REQ-NF-019`, `REQ-NF-021`, ADR-0009) |
| `docs/production-gaps.md` | ready | Every POC shortcut and what production would require |
| `docs/glossary.md` | ready | Terminology |
| `docs/requirements/functional-and-nonfunctional.md` | ready | `REQ-F-*` / `REQ-NF-*` capability list with milestone status |

## Development

| Document | Status | What it answers |
| --- | --- | --- |
| `AGENT.md` §5–§13 | ready | Layout, stack, configuration, workflow, testing, conventions, commits |
| `README.md` | ready | Positioning, quickstart, repository tour, non-goals |
| `CONTRIBUTING.md` | ready | How to work in this repository |
| `docs/specs/index.md` | ready | Normative references |
| `docs/specs/message-samples/` | ready | Real SIP messages on the trunk, generated with `make capture` and gitignored (only the folder `README.md` is tracked); the `office-to-mobile` call is 14 files, the translated outbound INVITE included. The anti-fraud AS's own calls are narrated live by `make demo-fraud`, and the chained `SBC -> anti-fraud -> number translation -> core` topology by `make demo-chained` |
| `tools/README.md` | ready | Probe, rule viewer, capture helper and the call capture tool |

## Deployment and operations

| Document | Status | What it answers |
| --- | --- | --- |
| `docs/operations/deployment.md` | ready | Topology, port matrix, resource profile, startup, health checks |
| `docs/operations/runbook.md` | ready | Routine operations: start/stop, reload rules, inspect state, log locations |
| `docs/operations/troubleshooting.md` | ready | Symptom -> cause -> action, keyed by `AS-*` error code |

## Acceptance and demo

| Document | Status | What it answers |
| --- | --- | --- |
| `docs/acceptance/criteria.md` | ready | `ACC-*` items with verification commands; M0–M3 accepted, M4 executed |
| `docs/acceptance/report.md` | ready | M0–M4 results with evidence |
| `docs/demo-script.md` | ready | The 5–10 minute narrated demo; every section runs today, the console included |
| `docs/demo-steps.md` | ready | The one-page copy-pasteable command checklist for the demo |
| `docs/roadmap.md` | ready | Milestone status, handover notes, open items |
| `docs/phase2-plan.md` | ready | Phase 2: strategic decisions, the P8a–P11 work sequence, repository and branch strategy. The single detailed source for what follows P1–P7 — `docs/roadmap.md` links here instead of duplicating it. **The full text lives on the `phase2` branch**; the copy on `main` is a stub that points there |
| `CHANGELOG.md` / `VERSION` | ready | Version history and the current version |
