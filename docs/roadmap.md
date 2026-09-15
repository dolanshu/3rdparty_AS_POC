# Roadmap and handover board

**This is the live status board for the project.** `AGENT.md` §15 states the fixed scope
of each milestone; this file records where each milestone actually stands, what was left
open, and what the next conversation needs to know.

## How to use it

Each milestone is executed in its own conversation.

**Opening ritual** (first message of a milestone conversation):

1. Read `AGENT.md`
2. Read `docs/README.md`
3. Read the milestone section below (status, exit criteria, handover notes, open items)
4. Read `docs/acceptance/criteria.md` for the acceptance items owned by that milestone

**Closing ritual**:

1. Run the DoD (`AGENT.md` §16), record results in `docs/acceptance/report.md` with
   evidence per `AGENT.md` §4.8
2. Update this file: status, handover notes, open items, entry state for the next
   milestone
3. Update `CHANGELOG.md` and `VERSION`; commit with the milestone scope prefix
   (`feat(m2): ...`); tag `v<version>-m<n>`
4. Write down anything a fresh conversation would otherwise re-derive

**Status values:** `not started` · `in progress` · `blocked` · `done`

## Current state

| Milestone | Status | Tag |
| --- | --- | --- |
| M0 — Foundation | done (2026-09-16) | pending (tagging is done by the maintainer) |
| M1 — Signalling path | not started | — |
| M2 — Number translation | not started | — |
| M3 — Console | not started | — |
| M4 — Acceptance and polish | not started | — |

## Environment (verified 2026-09-16)

- Python **3.10.12** is the interpreter available on this machine; the project targets it
- **`uv` 0.12.15 is installed** (`pip install uv`, done in M0) and is the toolchain in use
- `sippy` 2.4.2 installs cleanly on 3.10.12 and runs a minimal stack (see ADR-0001 and the
  probe output in `docs/acceptance/report.md`)
- Note for slow networks: this machine reaches `pypi.org` very slowly. Local runs used
  `UV_DEFAULT_INDEX=https://<mirror>/pypi/simple uv sync`; the committed `uv.lock`
  references the public PyPI, so CI and a clean checkout are unaffected.

## M0 — Foundation

**Status:** done (2026-09-16) — all exit criteria met, gates green, acceptance items
executed with evidence in `docs/acceptance/report.md`. Tagging is the maintainer's step
(agents do not tag).

**Scope** (from `AGENT.md` §15): telecom-grade skeleton `config/ deploy/ src/ tests/
tools/`; `pyproject.toml` + lock file; ruff/mypy/pytest config; CI workflow; meta files
(VERSION, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, NOTICE); `docs/` baseline;
sample routing data per `AGENT.md` §4.6; compose network with UDP ports; `.env.example`;
README quickstart; sippy-on-Python-3.10 verification. No call logic.

**Entry criteria:** repository containing `AGENT.md` and `LICENSE`. (The temporary domain
summary document that was used to define the problem space has been removed; the domain
context now lives in `AGENT.md` §1 and in the ADRs.)

**Exit criteria:**

- [x] Directory skeleton created exactly as `AGENT.md` §5
- [x] `uv` installed and locked; `uv sync` works from a clean checkout
      (`uv sync --frozen` and `uv lock --check` both pass)
- [x] sippy 2.4.2 verified: installs and runs a minimal stack on Python 3.10
      (`tools/sippy_probe.py`, real request/response exchange, exit code 0)
- [x] ruff / mypy / pytest configured and running (100 tests pass, 4 e2e cases skipped
      until M1)
- [x] CI workflow present, running lint / type / unit / integration / e2e layers
- [x] Meta files present: VERSION, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY,
      NOTICE
- [x] `docs/` baseline complete per `AGENT.md` §4.2 (see `docs/README.md` for status)
- [x] Sample routing data meets `AGENT.md` §4.6 (17 rules, 6 next hops, four number
      formats, priority + failover)
- [x] `README.md` quickstart written; `docs/README.md` up to date
- [x] `docs/acceptance/criteria.md` populated with M0 acceptance items
- [x] ADR-0002 … ADR-0006 written (`AGENT.md` §4.5)

**Done in this conversation (2026-09-15):**

- `AGENT.md` rewritten: IMS/SIP positioning, delivery standards (§4), telecom-grade
  layout (§5), acceptance and DoD (§11, §16), handover protocol (§15)
- `AGENT.md` §1 hardened with decisions that were previously implicit: B2BUA only (no
  `302` redirect mode), mock S-SBC on the same stack as the AS, rules read-only on the
  console
- `docs/architecture/adr/0001-use-sippy-as-sip-stack.md` — sippy decision plus all
  measured facts (version, licence, dependencies, Python 3.10 install, programming
  model, blocking event loop)
- `docs/specs/index.md` — normative references
- `docs/specs/message-samples/README.md` — sample capture conventions
- `docs/README.md` — documentation map by audience
- `docs/roadmap.md` — this board

**Done in this conversation (2026-09-16):**

- Skeleton per `AGENT.md` §5: `config/ deploy/ docs/ src/ tests/ tools/`, with
  `src/as_app/` (main, bootstrap, call_controller, sip_adapter, errors,
  routing/{rules,engine}, observability/{logging,metrics,tracing}, internal_api),
  `src/console/`, `src/s_sbc_mock/` and the three test layers
- `pyproject.toml` + committed `uv.lock`; ruff (format + lint), mypy, pytest configured
- CI workflow with the five layers; meta files; README with quickstart and repository tour
- Documentation baseline: SRS, HLD, LLD, ADR-0002 … ADR-0006, operations guides,
  acceptance criteria and report, demo script, glossary, production gap register
- Sample routing data (17 rules, 6 next hops) plus the Pydantic model, loader and reload
  detection
- `deploy/docker-compose.yml` with `as`, `s-sbc-mock` and `console` and one Dockerfile
  each; `tools/{sippy_probe.py,show_rules.py,capture.sh}`
- M0 acceptance run: 12 of 12 items accepted, evidence in `docs/acceptance/report.md`

**Handover notes (read this before starting M1):**

- **Toolchain actually used: `uv` 0.12.15**, installed with `pip install uv`. The project
  is installed editable, so `uv sync` alone is enough: `uv run python -m as_app.main`
  works without setting `PYTHONPATH`. The maintainer-approved `venv` + `pip` fallback was
  **not** needed.
- **sippy verification result: passed.** `uv run python tools/sippy_probe.py` starts
  `SipConf` + `SipTransactionManager` + `ED2.loop()` on loopback, sends one INVITE
  (`Call-ID: probe-17442@example.invalid`) and receives `SIP/2.0 404 Probe` with a
  generated `To` tag; the last line is
  `minimal SipTransactionManager + ED2.loop() stack: OK`, exit code 0. Full output is in
  `docs/acceptance/report.md`.
- **Two sippy facts discovered while probing** (they are in
  `docs/operations/troubleshooting.md` as well):
  - `ED2.loop()` must run on the main thread; running it in a worker thread produces
    `Timer.go() from wrong thread, expect Bad Stuff to happen`.
  - `global_config['_sip_logger']` must be set (`SipLogger('as')`); `None` raises
    `AttributeError` on the first inbound message.
- **The `logging` shadowing issue is still open for M1** (see open items below).
- **`make demo` is a stub** in M0: it prints the rule set and the decisions. The call demo
  and the four e2e cases are M1/M2 work; they are declared and skipped, not deleted.
- The default catch-all rule `R-DEFAULT-99` is present but **disabled** so that the
  no-match `404` branch stays demonstrable. Enable it to route every remaining number.

**Open items:**

- **Resolved (maintainer, 2026-09-16): `src/as_app/observability/logging.py` keeps its
  name.** Ruled on after M0 flagged that it shadows the stdlib `logging` module. The
  binding rule is now in `AGENT.md` §5: all imports of it are package-absolute, and
  `src/as_app/observability/` is never put on `sys.path`. M1 must respect this; the trap
  itself is documented in `docs/architecture/lld.md` section 8.
- **The configuration model lives in `bootstrap.py`** (startup parsing is a startup
  concern). If it grows in M1, move it to its own module and update `AGENT.md` §5 —
  recorded in `docs/architecture/lld.md` section 1.1.
- **No CI runner in this environment**: the workflow is committed and its commands were
  executed locally, but no CI badge or run link exists yet. A green run should be recorded
  in `docs/acceptance/report.md` when the repository is pushed.
- **`uv` needs a package index mirror on this machine** (`UV_DEFAULT_INDEX=...`); the
  committed lock refers to the public PyPI, so this is local-only.
- **Unused runtime dependencies**: sippy pulls in `rtpsynth`, `g722`, `flask` and
  `flask-login`, which this signalling-only service never imports. Registered in
  `docs/production-gaps.md`.

**Entry state for M1:** `uv sync --frozen` works, all gates pass, the rule set loads and
reloads, and the sippy stack is proven to run. What M1 has to add is the transaction
manager wiring, the call control hook and the two mock sides.

**Previously open, resolved in M0:**

- **Toolchain fallback: `venv`.** `uv` was installed successfully, so the fallback was not
  used. It stays approved for environments where `uv` cannot be installed.
- **Remaining ADRs: write them.** ADR-0002 … ADR-0006 are written.

## M1 — Signalling path

**Status:** not started

**Scope:** AS boots on sippy; mock S-SBC sends INVITE; a full call completes
(`100 -> 180 -> 200 -> ACK -> BYE`) with headers and SDP passed through; structured
logging, counters, health endpoint and graceful shutdown in place. Console not yet
connected.

**Entry criteria:** M0 done; `uv sync` works; sippy verified.

**Exit criteria:**

- [ ] AS process starts, binds UDP, and answers an INVITE from the mock
- [ ] Complete call flow including BYE, verified by e2e test
- [ ] Headers and SDP pass through unmodified (asserted in integration tests)
- [ ] Structured logging with Call-ID correlation
- [ ] Counters exposed; health endpoint live; `SIGTERM` shuts down gracefully
- [ ] Acceptance items for M1 recorded with evidence

**Handover notes:** _to be filled when the milestone ends_

**Open items:** none yet

## M2 — Number translation

**Status:** not started

**Scope:** rule engine with YAML hot reload; Request-URI and number format rewriting
inside `CallController`; error branches (`404`, `603`, `CANCEL`); error code system;
unit + integration + e2e tests; first acceptance run.

**Entry criteria:** M1 done; call flow stable.

**Exit criteria:**

- [ ] Rules loaded from `config/` with hot reload
- [ ] Translation applied to Request-URI and number formats (E.164, `0`-prefixed, short
      codes, international `00`)
- [ ] Multiple next hops with priority and failover
- [ ] Error branches `404` / `603` / `CANCEL` covered by tests
- [ ] Error code system (`AS-*`) implemented and documented in the LLD
- [ ] Unit, integration and e2e layers green

**Handover notes:** _to be filled when the milestone ends_

**Open items:** none yet

## M3 — Console

**Status:** not started

**Scope:** internal REST + WebSocket API; telecom-operations UI per `AGENT.md` §4.4; live
message flow; payload viewer; rule-hit display; statistics dashboard; SVG topology.

**Entry criteria:** M2 done; counters and trace already exposed by the AS.

**Exit criteria:**

- [ ] Internal API serves call trace, rules, configuration and statistics
- [ ] UI meets `AGENT.md` §4.4 (dark console theme, status bar, navigation, live flow,
      rule highlight, statistics, SVG topology)
- [ ] No third-party front-end libraries
- [ ] Console runs as a separate process (per ADR-0002)

**Handover notes:** _to be filled when the milestone ends_

**Open items:** none yet

## M4 — Acceptance and polish

**Status:** not started

**Scope:** full acceptance run with evidence per `AGENT.md` §4.8; demo script rehearsal;
ADR and documentation review; tagged release.

**Entry criteria:** M3 done.

**Exit criteria:**

- [ ] Every acceptance item executed with the four kinds of evidence
- [ ] `docs/demo-script.md` rehearsed end to end
- [ ] Documentation review pass: no stale samples, no broken links, no unregistered gaps
- [ ] Version tagged and release notes published

**Handover notes:** _to be filled when the milestone ends_

**Open items:** none yet

## Conventions

- **Single source of truth:** rules live in `AGENT.md`; live status lives here; evidence
  lives in `docs/acceptance/report.md`
- **Commit scope:** `feat(m2): ...`, `fix(m1): ...`
- **Version and tag:** one version node per milestone, tag `v<version>-m<n>`
- **Decisions:** recorded as ADRs in `docs/architecture/adr/`, referenced from code
