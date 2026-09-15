# Documentation map

Start with `AGENT.md`. It defines the rules, the standards and the handover protocol.
This page is the index of everything else, grouped by what a reader is trying to do.

Legend: **ready** — exists and is usable · **skeleton** — exists, content pending ·
**planned** — not created yet.

## Architecture review

| Document | Status | What it answers |
| --- | --- | --- |
| `AGENT.md` §1–§5, §15 | ready | Positioning, boundaries, non-goals, delivery standards, roadmap |
| `docs/architecture/hld.md` | ready | System context, deployment view, interface view, quality attributes, key flows |
| `docs/architecture/lld.md` | ready | Modules, data structures, state machines, error codes, process model, log fields |
| `docs/architecture/adr/` | ready | ADR-0001 … ADR-0006: sippy, process separation, UDP only, YAML rules, mock strategy, signalling only |
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
| `docs/specs/message-samples/` | ready | Real SIP messages on the trunk; the `office-to-mobile` call is captured in 14 files, the translated outbound INVITE included |
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
| `docs/acceptance/criteria.md` | ready | `ACC-*` items with verification commands; M0–M2 accepted, M3/M4 planned |
| `docs/acceptance/report.md` | ready | M0–M2 results with evidence; M3/M4 pending |
| `docs/demo-script.md` | ready | The 5–10 minute narrated demo; sections 1–5 run today, the console section needs M3 |
| `docs/roadmap.md` | ready | Milestone status, handover notes, open items |
| `CHANGELOG.md` / `VERSION` | ready | Version history and the current version |
