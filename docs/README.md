# Documentation map

Start with `AGENT.md`. It defines the rules, the standards and the handover protocol.
This page is the index of everything else, grouped by what a reader is trying to do.

Legend: **ready** — exists and is usable · **skeleton** — exists, content pending ·
**planned** — not created yet.

## Architecture review

| Document | Status | What it answers |
| --- | --- | --- |
| `AGENT.md` §1–§5, §15 | ready | Positioning, boundaries, non-goals, delivery standards, roadmap |
| `docs/architecture/hld.md` | planned | System context, deployment view, interface view, quality attributes |
| `docs/architecture/lld.md` | planned | Modules, data structures, state machines, error codes, process model |
| `docs/architecture/adr/` | in progress | Decisions and consequences — ADR-0001 (sippy) is ready |
| `docs/production-gaps.md` | planned | Every POC shortcut and what production would require |
| `docs/glossary.md` | planned | Terminology |

## Development

| Document | Status | What it answers |
| --- | --- | --- |
| `AGENT.md` §5–§13 | ready | Layout, stack, configuration, workflow, testing, conventions, commits |
| `docs/specs/index.md` | ready | Normative references |
| `docs/specs/message-samples/` | ready (convention) | Real SIP messages on the trunk |
| `CONTRIBUTING.md` | planned | How to work in this repository |
| `docs/requirements/functional-and-nonfunctional.md` | planned | `REQ-*` capability list |

## Deployment and operations

| Document | Status | What it answers |
| --- | --- | --- |
| `docs/operations/deployment.md` | planned | Topology, port matrix, startup, health checks |
| `docs/operations/runbook.md` | planned | Routine operations |
| `docs/operations/troubleshooting.md` | planned | Symptom -> cause -> action |

## Acceptance and demo

| Document | Status | What it answers |
| --- | --- | --- |
| `docs/acceptance/criteria.md` | planned | `ACC-*` items with verification commands |
| `docs/acceptance/report.md` | planned | Results and evidence |
| `docs/demo-script.md` | planned | The 5–10 minute narrated demo |
| `docs/roadmap.md` | ready | Milestone status, handover notes, open items |
| `CHANGELOG.md` / `VERSION` | planned | Version history and the current version |
