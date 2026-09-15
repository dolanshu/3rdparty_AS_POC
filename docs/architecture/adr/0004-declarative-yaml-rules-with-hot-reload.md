# ADR-0004: Declarative YAML routing rules with reload

- **Status:** Accepted
- **Date:** 2026-09-15
- **Deciders:** project maintainer
- **Related:** `AGENT.md` section 1, 4.6 and 5, `docs/architecture/lld.md` section 2

## Context

Number translation and routing is the service this AS provides. The POC has to prove that
the policy can be changed **without touching code**, and the sample data has to look like
a real office dial plan (10–20 rules, several operators, special service numbers, at
least two next hops with priority and failover).

Options considered:

| Option | Assessment |
| --- | --- |
| Policy in Python (`if`/`elif` chains) | Fast to write, but every change is a code change, a review and a deploy |
| Rules in a database with a CRUD UI | Realistic for production, but adds persistence, a UI and a migration to a POC whose point is the call path |
| **Declarative YAML file, validated on load** | Data, not code; diffable in review; loadable and testable in milliseconds; no new runtime component |

## Decision

The routing policy is a **YAML document** (`config/routing_rules.yaml`) with:

- a next hop catalogue (name, address, port, transport, priority),
- rules with `rule_id`, `priority`, `description`, `enabled`, `tags`, a `match` block
  (`called_prefixes`, `called_numbers`, `number_format`) and a discriminated `action`
  (`route` with a `translate` block and an ordered next hop list, or `reject` with a
  status and an error code).

The document is parsed and validated by Pydantic models in
`src/as_app/routing/rules.py`; failures are reported as `AS-RULE-00x`, never as raw
exceptions. `RuleSetStore` detects a changed file (size and modification time) and
activates the new rule set; if the new file is invalid, the **previous rule set stays
active** and the error is logged.

Rules are **read-only on the console**: they are edited as data files under `config/`
and never through the UI.

## Consequences

- **Policy changes are reviewable diffs** and can be tested by the unit layer.
- **Fail-safe reload:** a broken edit cannot take the service down, because the old rule
  set remains in memory.
- **The decision logic stays pure.** `routing/engine.py` has no sockets, no global state
  and no clock, so the whole policy is unit-testable.
- **Reload is pull-based**, not a filesystem watcher: the sippy thread must not be blocked
  by file I/O, so the process that owns the loop decides when to poll.

## Gaps accepted

- No rule provenance, no author, no approval workflow.
- No per-tenant rule sets and no atomic swap across a cluster (single process).
- A YAML file is not a managed configuration service; see `docs/production-gaps.md`.
