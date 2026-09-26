---
name: feature-delivery
description: >-
  Deliver a formal repo feature through staged artifacts (requirements, ADR, design,
  testing plan, coding, testing) with a review gate and fresh subagent per stage.
  Use when starting a new feature, a multi-phase feature (A then B), or when the user
  asks for requirement/ADR/design/testing_plan/coding/testing with reviews.
disable-model-invocation: true
---

# Feature delivery (staged subagents)

**Leading word: _stage_** — one artifact set per stage; the parent orchestrates, subagents execute; **review** is always a separate subagent.

## When to use

- New user-visible capability or cross-cutting console/API change
- Multi-phase delivery (e.g. Phase A UI, Phase B backend) where later work must extend earlier seams
- User explicitly requires: requirement → ADR → design → testing_plan → coding → testing, each with review

## Parent agent rules

1. **Do not implement across stages in one context.** Dispatch one subagent per stage; pass only the artifact paths and acceptance criteria for that stage.
2. **Review is mandatory** before the next stage starts. Use a **fresh** subagent (`subagent_type: generalPurpose` or `explore` for read-only review).
3. **Carry forward only:** approved artifact paths, REQ/ACC IDs, ADR number, open review findings marked fixed.
4. **Feature folder:** `docs/features/<feature-slug>/` — all stage outputs live here plus updates to canonical docs (`docs/requirements/`, `docs/architecture/adr/`, `docs/acceptance/criteria.md`, testing plans).

## Stage sequence

| Stage | Artifact | Executor | Review focus |
| --- | --- | --- | --- |
| 1 | Requirements (`REQ-*`, `ACC-*` draft) | subagent | Traceability, testability, scope vs non-goals |
| 2 | ADR | subagent | Decision recorded, alternatives, consequences, gaps |
| 3 | Design (`design.md`, HLD/LLD deltas) | subagent | Feasibility, seams for later phases, no scope creep |
| 4 | Testing plan | subagent | Layer coverage, commands, negative cases |
| 5 | Coding (Phase A) | subagent | Matches design; minimal diff |
| 6 | Testing (Phase A) | subagent | Tests green; plans updated |
| 7 | Review gate A | review subagent | Standards + spec (use `code-review` skill if available) |
| 8 | Coding (Phase B) — if applicable | subagent | Extends Phase A seams only |
| 9 | Testing (Phase B) | subagent | API + UI regression |
| 10 | Review gate B | review subagent | Security, payload exposure, memory bounds |
| 11 | Acceptance closure | subagent | `criteria.md`, `report.md`, `production-gaps.md`, README index |

Skip stages 8–10 when the feature is single-phase. Never skip review after 5–6 or 8–9.

## Subagent dispatch template (executor)

```
Full Repository Path: /home/shudong/project/3rdparty_AS_POC
Feature slug: <slug>
Stage: <N> — <name>
Read first:
- AGENT.md §4–§5, §13, §16
- docs/features/<slug>/plan.md
- <prior stage artifact paths>

Deliver:
- <exact files to create or update>
- Do NOT start later stages
- Do NOT commit unless user asked

Completion criterion:
- All listed files exist and cross-reference REQ/ACC/ADR IDs
- Run: <verification command> and report pass/fail
```

## Subagent dispatch template (review)

```
Full Repository Path: /home/shudong/project/3rdparty_AS_POC
Stage under review: <N> — <name>
Artifacts: <paths>
Prior stage artifacts: <paths>

Review against:
- docs/features/<slug>/plan.md exit criteria for this stage
- AGENT.md presentation + testing standards
- REQ/ACC traceability

Output format:
## Verdict: APPROVE | REVISE
## Blockers (must fix before next stage)
## Non-blockers
## Traceability gaps
```

## Canonical doc updates (every feature)

| Doc | When |
| --- | --- |
| `docs/requirements/functional-and-nonfunctional.md` | Stage 1 |
| `docs/architecture/adr/00NN-*.md` | Stage 2 |
| `docs/architecture/hld.md` / `lld.md` | Stage 3 (short delta or pointer) |
| `docs/testing/unit-plan.md`, `integration-plan.md`, `e2e-playwright-plan.md` | Stage 4 |
| `docs/acceptance/criteria.md` | Stage 1 draft; Stage 11 final |
| `docs/production-gaps.md` | Stage 2 or 3 when accepting POC shortcuts |
| `docs/README.md` | Stage 11 — index feature folder |

## Anti-patterns

- Parent implements Stage 5 after writing Stage 3 in the same thread → **context pollution**
- Skipping review because "small change" → **violates this skill**
- Phase B rewrites Phase A rendering (new chart lib, new data source) → **duplicate work**; design must reuse SVG/modal seams
- Adding vendored JS without ADR → **blocks merge**

## Reference

- Stage checklists and file templates: [reference.md](reference.md)
- Example feature: `docs/features/call-trace-message-flow/`
