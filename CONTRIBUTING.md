# Contributing

This repository is a proof of concept that is read by architecture reviewers. Presentation
is part of the deliverable: a change that works but leaves the documentation chain stale
is an incomplete change.

## Read first

1. `AGENT.md` — the rules of engagement, the delivery standards (section 4), the layout
   (section 5), the testing strategy (section 11), the coding conventions (section 12) and
   the commit rules (section 13).
2. `docs/README.md` — the documentation map by audience.
3. `docs/roadmap.md` — the milestone that is currently open, its exit criteria and its
   open items.

## Environment

```bash
pip install uv          # or use the fallback below
uv sync                 # creates .venv and installs the locked environment
make lint               # ruff format --check + ruff check + mypy
make test               # unit + integration + e2e
```

Fallback without `uv` (approved by the maintainer, see `docs/roadmap.md`):

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt   # exported with: uv export --no-dev --format requirements-txt
```

Python **3.10** is required. sippy is pinned at **2.4.2**; do not upgrade it without
asking the maintainer.

## Before you open a change

- `make lint` and `make test` are green.
- New behaviour walks the documentation chain: requirement (`REQ-*`) → design (HLD/LLD) →
  message samples → acceptance item → CHANGELOG.
- New configuration knobs are added to `.env.example`, `README.md` and
  `docs/operations/deployment.md`.
- New POC shortcuts are registered in `docs/production-gaps.md`.
- Structural changes (new directory, renamed configuration field, new port or service)
  update `AGENT.md`, `README.md` and `docs/README.md` in the same change.

## Commits

Conventional Commits in English, one logical change per commit:
`feat` · `fix` · `docs` · `refactor` · `test` · `chore` · `build`. Milestone work carries
the milestone prefix, for example `feat(m2): apply number translation in CallController`.

## Code style

- Type hints on all public functions; `mypy` must stay clean.
- English identifiers, comments, log messages and error strings.
- Domain naming: no `util`, `helper`, `misc` or `common` modules.
- Routing decisions are pure functions in `src/as_app/routing/engine.py`; sippy glue stays
  thin in `sip_adapter.py` and `call_controller.py`.
- Reference the decision you are implementing: `# See ADR-0003`.

## Never do

- Never commit secrets, certificates, environment files or captures of real traffic.
- Never invent SIP behaviour: check RFC 3261, the sippy source, or write a probe under
  `tools/` and observe.
- Never claim verified behaviour that was not executed.
