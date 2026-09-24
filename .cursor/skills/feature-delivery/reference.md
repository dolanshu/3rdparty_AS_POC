# Feature delivery — reference

## Feature folder layout

```
docs/features/<feature-slug>/
├── plan.md           # Master plan, phases, stage status, subagent log
├── design.md         # Console/API/UI behaviour, data flow, seams
├── testing-plan.md   # Unit / integration / e2e matrix for this feature
└── reviews/          # Optional: paste review subagent outputs per stage
    ├── stage-01-requirements.md
    └── ...
```

## Stage exit criteria (checklist)

### Stage 1 — Requirements

- [ ] New `REQ-F-*` / `REQ-NF-*` rows with status `planned` or `accepted`
- [ ] Draft `ACC-*` rows with verification command
- [ ] REQ-F-012 or related reqs cross-referenced if restoring partial capability
- [ ] Phase B reqs marked `planned` when deferred

### Stage 2 — ADR

- [ ] `docs/architecture/adr/00NN-*.md` with Status, Context, Decision, Consequences, Alternatives
- [ ] `docs/production-gaps.md` row for each accepted POC shortcut
- [ ] `docs/README.md` ADR index line updated (Stage 11 if ADR merged early)

### Stage 3 — Design

- [ ] `design.md`: actors, data sources, UI states, error/empty/loading
- [ ] Explicit **Phase A / Phase B seams** (functions, API shapes, DOM ids)
- [ ] HLD or LLD pointer section (≤30 lines delta, not duplicate HLD)

### Stage 4 — Testing plan

- [ ] New tests named with file paths
- [ ] Updates to `docs/testing/*-plan.md` counts
- [ ] Commands for CI parity (`uv run pytest …`)

### Stages 5–6 — Phase A code + tests

- [ ] Implementation matches design seams
- [ ] Tests pass locally
- [ ] No Phase B scope in diff

### Stage 7 — Review A

- [ ] Verdict APPROVE or blockers listed and fixed in a **new** executor subagent

### Stages 8–10 — Phase B (optional)

- [ ] Backend API + console modal extension only
- [ ] No redo of sequence SVG layout

### Stage 11 — Acceptance

- [ ] `docs/acceptance/criteria.md` final
- [ ] Evidence snippet in `docs/acceptance/report.md` (maintainer may expand)
- [ ] `CHANGELOG.md` / `VERSION` only if user requested release prep

## REQ row template

```markdown
| REQ-F-0NN | <one sentence capability> | planned | P15 | ACC-P15-00X |
```

## ACC row template

```markdown
| ACC-P15-00X | <criterion> | `<verification command>` | <evidence shape> | REQ-F-0NN |
```

## ADR title template

`00NN-<kebab-case-decision>.md`

## Review verdict rules

- **APPROVE:** zero blockers; non-blockers may ship
- **REVISE:** one or more blockers; re-run executor subagent with blocker list only; re-run review subagent (fresh)
