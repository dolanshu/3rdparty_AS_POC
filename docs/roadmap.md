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
| M0 — Foundation | in progress (documentation baseline) | — |
| M1 — Signalling path | not started | — |
| M2 — Number translation | not started | — |
| M3 — Console | not started | — |
| M4 — Acceptance and polish | not started | — |

## Environment (verified 2026-09-15)

- Python **3.10.12** is the interpreter available on this machine; the project targets it
- **`uv` is not installed** — M0 must install it (or fall back to `venv` + `pip`) before
  anything can be run
- `sippy` 2.4.2 installs cleanly on 3.10.12 (see ADR-0001)

## M0 — Foundation

**Status:** in progress (documentation baseline)

**Scope** (from `AGENT.md` §15): telecom-grade skeleton `config/ deploy/ src/ tests/
tools/`; `pyproject.toml` + lock file; ruff/mypy/pytest config; CI workflow; meta files
(VERSION, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, NOTICE); `docs/` baseline;
sample routing data per `AGENT.md` §4.6; compose network with UDP ports; `.env.example`;
README quickstart; sippy-on-Python-3.10 verification. No call logic.

**Entry criteria:** repository containing `AGENT.md` and `LICENSE`. (The temporary domain
summary document that was used to define the problem space has been removed; the domain
context now lives in `AGENT.md` §1 and in the ADRs.)

**Exit criteria:**

- [ ] Directory skeleton created exactly as `AGENT.md` §5
- [ ] `uv` installed and locked; `uv sync` works from a clean checkout
- [ ] sippy 2.4.2 verified: installs and runs a minimal stack on Python 3.10
- [ ] ruff / mypy / pytest configured and running (even with no tests yet)
- [ ] CI workflow present, running lint / type / unit / integration / e2e layers
- [ ] Meta files present: VERSION, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY,
      NOTICE
- [ ] `docs/` baseline complete per `AGENT.md` §4.2 (see `docs/README.md` for status)
- [ ] Sample routing data meets `AGENT.md` §4.6
- [ ] `README.md` quickstart written; `docs/README.md` up to date
- [ ] `docs/acceptance/criteria.md` populated with M0 acceptance items
- [ ] ADR-0002 … ADR-0006 written (`AGENT.md` §4.5)

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

**Handover notes:**

- Scope and standards are settled; do not re-open them without the maintainer
- The remaining M0 work is mechanical: skeleton, toolchain, docs baseline, sample data
- An `uv` installation step is required before any Python command works

**Open items:** resolved by the maintainer (2026-09-15).

- **Toolchain fallback: `venv`.** `uv` is the primary tool (0.12.15 is available on
  PyPI). If `uv` cannot be installed in a target environment, fall back to `venv` +
  `pip` with an exported requirements file. Which one was actually used is recorded in
  the M0 handover notes.
- **Remaining ADRs: write them.** ADR-0002 (process separation between AS and console),
  ADR-0003 (UDP-only transport), ADR-0004 (declarative YAML rules with hot reload),
  ADR-0005 (mock strategy for the S-SBC) and ADR-0006 (signalling-only scope) are part
  of the M0 documentation baseline (`AGENT.md` §4.5). ADR-0001 (sippy) is written.

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
