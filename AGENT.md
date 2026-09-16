# AGENT.md — 3rd-party AS POC

> Rules of engagement for humans and AI agents in this repository.
> Read this file **before** writing any code. If a rule here conflicts with a request,
> follow this file and raise the conflict with the maintainer.

## 1. Purpose & Scope

This repository is a **Proof of Concept of a third-party Application Server (AS) that
lives outside the operator's IMS network** and is reached through a SIP trunk from the
operator's Service-SBC.

This is an **IMS/SIP** POC, **not** a 5G capability exposure (CAPIF/NEF) POC.

**Stance: we implement the external AS.** We do not implement the S-SBC, the S-CSCF or
any core network element. The S-SBC and the core network behind it are replaced by a
local mock, and every peer address is configuration, so the same code can be pointed at
a real S-SBC by changing configuration only.

```text
        operator IMS core                    SIP trunk                  us
 +-------------------------------+                          +----------------------+
 |  S-CSCF ---ISC--- S-SBC       | ======================== | 3rd-party AS (B2BUA)|
 +-------------------------------+        UDP / 5060        +----------------------+
      (mocked: UAC + UAS side)                                  (this repository)
```

Boundaries that define our position:

- The S-SBC **impersonates an internal AS** towards the S-CSCF (iFC-triggered over ISC)
  and **impersonates a core network node** towards us. We only ever see the trunk side.
- We are a **B2BUA, and only a B2BUA**: we terminate the incoming INVITE, apply number
  translation and routing, then originate a new INVITE back to the S-SBC. A
  redirect-server mode (`302 Moved Temporarily`) is explicitly **not** implemented.
- SDP bodies and SIP headers are **passed through verbatim**; only the Request-URI and
  the number format (E.164 <-> local format) are rewritten.
- The service is **signalling-only** — no RTP, no media anchoring, no MRF.
- The mock S-SBC is built on the **same SIP stack as the AS** (see ADR-0001), so both
  sides speak identical protocol behaviour.
- Routing rules are **read-only** on the console: rules are edited as data under
  `config/`, never through the UI.

**This project exists to be reviewed.** It is shown to architecture reviewers, to
operator-side audiences and as an open artefact. Correct behaviour alone is not enough:
the repository must read as a telecom-grade deliverable, not as a demo script. The
presentation requirements in §4 are as binding as the functional ones.

What the POC must prove, end to end:

1. The AS receives an INVITE from the S-SBC over a SIP trunk and drives a complete call
   (`INVITE -> 100 -> 180 -> 200 OK -> ACK -> BYE`).
2. Number translation and routing decisions are made by a **declarative rule set** that
   can be changed without touching code.
3. Failure branches behave correctly: no matching rule -> `404`, policy rejection ->
   `603`, caller abandons -> `CANCEL`.
4. Every message is observable: a structured, Call-ID keyed trace log, plus a Web console
   showing the live message flow and the rule that matched.

## 2. Non-Goals

Explicitly **out of scope**. They are not "forgotten" — each one is tracked in the
Production Gap Register (§3).

- **No real IMS core.** No S-CSCF, I-CSCF, HSS, MRF or real S-SBC; the mock only has to
  behave like one on the trunk.
- **No media.** No RTP handling, no transcoding, no DTMF, no MRF interaction.
- **No performance or capacity work.** No calls-per-second targets, no load tests, no
  benchmarking claims.
- **No production-grade HA, multi-tenancy or auditing.**
- **No charging.** No CDRs, no RADIUS, no settlement.
- **No transport beyond UDP.** TCP and TLS are not implemented.
- **No production deployment concerns** beyond a local `docker compose` demo.

## 3. Production Gap Register

**Rule: every POC simplification MUST be registered, not silently ignored.**
When code takes a shortcut, add or update a row in `docs/production-gaps.md` with
`POC behaviour | production requirement | why it differs`. A change that deepens a
shortcut without updating this register is an incomplete change.

Baseline entries (already known, must exist in `docs/production-gaps.md` from M0):

| Area | POC behaviour | Production requirement |
| --- | --- | --- |
| Transport | UDP only | UDP + TCP + TLS; TLS mandatory on public-internet trunks |
| Peer authentication | Source IP allowlist at most | IP allowlist + SIP Digest + TLS certificate (triple check) |
| Topology | Single peer, single trunk | Multiple S-SBC peers, failover routing |
| Core network | Mocked UAC/UAS in one process | Real S-CSCF, iFC triggering, subscription data |
| Header handling | Verbatim pass-through | Header normalisation, private extension stripping |
| Transactions | Happy path + a few error branches | Full RFC 3261 retransmission, timer and timeout handling |
| Reliability | Single process, no persistence | Restart safety, session recovery, watchdog |
| Media | None | SDP negotiation validation, optional media anchoring |
| Charging | None | CDR generation per call leg |
| Security | Local mock, dev-only | DoS protection, rate limiting, CAC, black/white lists |
| Observability | Console + log trace | Centralised collection, retention, alerting |
| Configuration | Local YAML + `.env.example` | Managed configuration service, secret manager |
| Capacity | Not measured | SLA-backed throughput and call setup latency |

## 4. Delivery & Presentation Standards

These rules exist because reviewers see the whole repository. A violation is a defect,
even when the code works.

### 4.1 Repository skeleton

The top level is fixed: `config/` `deploy/` `docs/` `src/` `tests/` `tools/` plus the
mandatory meta files listed in §4.7. Do not add ad-hoc top-level directories; do not
scatter Dockerfiles, compose files or scripts at the root.

### 4.2 Required documentation set

| Document | Purpose |
| --- | --- |
| `README.md` | Positioning, architecture diagram, quickstart, demo entry point, repository tour, non-goals, documentation index |
| `docs/README.md` | One-page navigation by audience: architecture review / development / deployment & operations / acceptance |
| `docs/requirements/functional-and-nonfunctional.md` | SRS-style capability list, IDs `REQ-F-001` / `REQ-NF-001`, each traceable to an acceptance item |
| `docs/architecture/hld.md` | High level design: system context, deployment view, interface view, quality attributes, constraints, key message flows |
| `docs/architecture/lld.md` | Low level design: module and class responsibilities, data structures, state machines, error code table, process model, configuration and log field reference |
| `docs/architecture/adr/NNNN-*.md` | Architecture decision records (see §4.5) |
| `docs/specs/index.md`, `docs/specs/message-samples/` | Normative references and real message samples |
| `docs/operations/deployment.md` | Deployment guide: topology, port matrix, resource profile, startup and shutdown, health checks |
| `docs/operations/runbook.md` | Routine operations: start/stop, reload rules, inspect state, log locations |
| `docs/operations/troubleshooting.md` | Symptom -> cause -> action runbook |
| `docs/acceptance/criteria.md` | Formal acceptance list, one row per item: criterion, verification command, expected result, related requirement |
| `docs/acceptance/report.md` | Result of the acceptance run with evidence (see §4.8) |
| `docs/demo-script.md` | 5–10 minute narration: what to run, what to say, what the reviewer should see |
| `docs/demo-steps.md` | Quick follow-along command checklist for the demo (companion to docs/demo-script.md) |
| `docs/glossary.md` | Terminology: IMS, S-SBC, ISC, iFC, B2BUA, E.164, IMPU, trunk, and so on |
| `docs/production-gaps.md` | The register from §3 |

All diagrams are **Mermaid or ASCII**, committed as text. No binary diagrams, no
rendered images that cannot be reviewed in a diff.

### 4.3 Code presentation standards

- **Error code system.** One authoritative error model in `src/as_app/errors.py`:
  internal codes (for example `AS-CFG-001`, `AS-RULE-002`, `AS-ROUTE-003`,
  `AS-PEER-004`) mapped to SIP status codes and log messages. The mapping is documented
  in the LLD and in the interface specification. No ad-hoc exceptions with bare strings.
- **Structured logging.** Every log line carries `timestamp`, `level`, `module`,
  `call_id`, `direction`, `peer`, and an event message. Call-ID threads the whole call
  across both legs. The field set is documented in the LLD and never changed silently.
- **File headers.** Every source file starts with the licence header and a short module
  responsibility statement. No anonymous modules.
- **Domain naming.** Names express the telecom domain (`NumberTranslationService`,
  `RoutingPlan`, `TrunkPeer`, `CallLeg`, `RuleMatch`). `util`, `helper`, `misc`,
  `common`, `tools`-style module names are **forbidden** in `src/`.
- **Runtime completeness.** Startup self-check (configuration schema, rules file parse
  and validation, port availability, peer configuration sanity), a health endpoint,
  graceful shutdown on `SIGTERM`/`SIGINT`, and fail-fast behaviour: an invalid
  configuration aborts startup rather than failing later at runtime.
- **Observability.** Built-in counters: total calls, calls by disposition, error code
  distribution, rule hit distribution, peer status. Exposed on the console dashboard
  together with a per-Call-ID trace view.
- **Design traceability.** Every non-obvious decision has an ADR; the code carries a
  short comment pointing at it (`# See ADR-0003`). Reviewers must be able to move from
  code to rationale in one step.

### 4.4 Console standard

The console is a product surface, not a debug page:

- Dark operations-console theme, consistent spacing and typography.
- Top status bar: peer state, version, uptime, live call counters.
- Left navigation: Call Trace / Rules / Configuration / Statistics / About.
- Centre panel: live message flow with direction and colour coding, Call-ID filter,
  payload viewer, and highlighting of the rule that matched.
- Small inline **SVG topology view** showing S-SBC <-> AS with the current call path.
- **No third-party front-end libraries**; plain HTML/CSS/JS only, so the demo works
  offline.

### 4.5 Architecture decision records

`docs/architecture/adr/0001-*.md` onward. At minimum: choice of sippy over a
hand-written stack, process separation between AS and console, UDP-only transport,
declarative YAML rules with hot reload, mock strategy for the S-SBC, and the
signalling-only scope. Each ADR records context, decision, consequences and the gaps it
accepts.

### 4.6 Sample data scale

The mock data must look like real office data, not like a unit test fixture:

- 10–20 translation/routing rules with priorities.
- Number ranges across multiple operators plus special service numbers.
- At least two next hops with priority and failover.
- Number formats: E.164 (`+86...`), national `0`-prefixed, short codes, international
  `00` prefix.

### 4.7 Versioning and meta files

- SemVer with a `VERSION` file, `CHANGELOG.md` (keep-a-changelog style), annotated tags
  `vX.Y.Z`. Each milestone ends at a tagged version.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `NOTICE` (third-party notices,
  including sippy's BSD-2-Clause attribution), `LICENSE`.
- CI workflow running the gates in layers: lint, type check, unit, integration, e2e.
  README carries the resulting status badges. Dependency lock is verified in CI.

### 4.8 Acceptance evidence

Every acceptance item in `docs/acceptance/report.md` carries evidence:

1. the verification command with its expected output (reproducible by the reviewer),
2. a real log excerpt keyed by Call-ID,
3. the CI result (badge, link or artefact),
4. the packet capture reference (pcap index and the key message excerpt).

An acceptance item without evidence is not accepted.

## 5. Architecture & Directory Layout

```text
AGENT.md  README.md  CHANGELOG.md  VERSION  CONTRIBUTING.md
CODE_OF_CONDUCT.md  SECURITY.md  NOTICE  LICENSE  Makefile  .env.example
config/                       routing rules and environment samples
src/as_app/                   the third-party AS (sippy application)
  main.py                     SipConf + SipTransactionManager + ED2.loop()
  bootstrap.py                startup self-check, signal handling, graceful shutdown
  call_controller.py          custom Call Control Logic — the business hook
  sip_adapter.py              thin wrapper around sippy primitives
  errors.py                   error model and code -> SIP status mapping
  routing/rules.py            YAML rule loading and hot reload
  routing/engine.py           pure functions: translate and route
  observability/logging.py    structured logging
  observability/metrics.py    counters and dispositions
  observability/tracing.py    per-Call-ID trace and console event feed
  internal_api.py             internal REST + WebSocket for the console
src/console/                  FastAPI + plain HTML/CSS/JS (separate process)
src/s_sbc_mock/               UAC (emulates S-CSCF trigger) + UAS (emulates core)
deploy/                       docker-compose.yml + per-service Dockerfiles
tools/                        capture, message generation and probe scripts
tests/unit/ tests/integration/ tests/e2e/
docs/                         see §4.2
```

**Rules for the layout:**

- `src/as_app/` must never import from `src/s_sbc_mock/` (tests excepted). The AS must
  be able to run against a real S-SBC without a code change.
- Business decisions live in `routing/engine.py` as **pure functions**; the sippy
  callbacks in `call_controller.py` stay thin glue. This is what makes the logic
  unit-testable without a network.
- sippy runs its **own blocking event loop** (`ED2.loop()`). It must never share a
  thread or an asyncio loop with the console; the two processes talk over the internal
  API only.
- `src/as_app/observability/logging.py` keeps its name **by maintainer decision**
  (2026-09-16); it shadows the stdlib module name, so every import of it must be
  package-absolute (`from as_app.observability.logging import ...`) and
  `src/as_app/observability/` must never be placed on `sys.path`. Renaming it is a
  structural change and requires the maintainer. See `docs/architecture/lld.md` §8.
- Adding, moving or renaming a directory or a configuration field is a **structural
  change** and must update this file, `README.md` and `docs/README.md` in the same
  commit (§12).

## 6. Tech Stack

Pinned; do not upgrade without asking.

- Python **3.10** (the version sippy has been verified against on this machine)
- **sippy 2.4.2** — RFC 3261 SIP stack and B2BUA framework (BSD-2-Clause)
- Console: **FastAPI** + uvicorn + plain HTML/CSS/JS, **no Node toolchain, no build
  step, no third-party front-end libraries**
- `uv` for environment and dependency management (`pyproject.toml` + `uv.lock`)
- pytest · `ruff` (format + lint) · `mypy`
- `docker compose` for the three-service demo

Constraints that shape the design:

- `ED2.loop()` blocks. Never call blocking operations from inside sippy callbacks.
- sippy pulls in media-related dependencies (`rtpsynth`, `g722`) although we do no media
  work. Do not work around it; record it in the gap register if it ever matters.
- sippy behaviour is verified **by running it**, not by assumption. When in doubt, write
  a small probe under `tools/` or `tests/` and observe the real behaviour.

## 7. Specifications & References

- **RFC 3261** — SIP (primary)
- **RFC 4566** — SDP (pass-through only)
- **RFC 3550** — RTP (background reading; not implemented)
- **3GPP TS 24.229** — IMS call control, iFC/ISC context
- **3GPP TS 23.228** — IMS architecture (context for where the S-SBC sits)

`docs/specs/index.md` lists each reference with version and retrieval date.
`docs/specs/message-samples/` holds representative trunk-side messages.

**Rules:**

- Method names, header names, status codes and URI syntax come from the RFC or from
  observed sippy behaviour — never from memory or plausibility.
- If a specification detail is unavailable or ambiguous, stop and ask.
- A message sample that no longer matches real traffic is a bug; regenerate it.

## 8. Configuration & Environments

All configuration via environment variables, declared in `.env.example`, parsed by
`pydantic-settings`. No default that silently points at a real network.

Key knobs (finalised in M0, kept in sync with `README.md` and the deployment guide):

- `SIP_LISTEN_ADDRESS`, `SIP_LISTEN_PORT` — where the AS receives the trunk
- `SBC_PEER_ADDRESS`, `SBC_PEER_PORT` — next hop (mock or real S-SBC)
- `RULES_FILE` — path to the routing rules file
- `ALLOWED_PEERS` — source addresses accepted on the trunk
- `INTERNAL_API_ADDRESS/PORT` — how the console reaches the AS
- `LOG_LEVEL`, payload logging switch

**Switching from mock to a real S-SBC must be a configuration change only.**

## 9. Security & Credentials

- **Nothing sensitive is ever committed** — no keys, certificates, tokens or real
  addresses. Only `.env.example` and generation scripts live in the repo.
- The mock stands in for an operator boundary. Treat the trunk as untrusted: verify the
  peer address against `ALLOWED_PEERS` and reject anything else.
- SIP Digest authentication and TLS are **not implemented**; both are registered in §3.
  Never imply otherwise in docs, logs or demos.
- Payload logging is explicit and switchable; the console may display payloads, the log
  must not do so by default.

## 10. Development Workflow

```bash
uv sync                  # install / sync the locked environment
make dev                 # run AS + mock locally
docker compose up        # as + s-sbc-mock + console
make demo                # one command: place a call, show the translated INVITE
make lint                # ruff format --check + ruff check + mypy
make test                # unit + integration + e2e
```

- Every dependency goes through `uv` and is committed with `uv.lock`.
- Code must run from a clean checkout: clone -> `uv sync` -> `make demo`. If that breaks,
  fixing it outranks adding features.
- M0 includes an explicit verification step that sippy and its dependencies install and
  run on Python 3.10 in this environment. If that fails, stop and escalate instead of
  silently changing versions.
- `make demo` is the rehearsed path from `docs/demo-script.md`. If the script and the
  command disagree, both are wrong until fixed.

## 11. Testing Strategy, Acceptance & Definition of Done

Three layers; all must pass before any commit:

1. **Unit** (`tests/unit/`) — rule loading and matching, number/URI translation as pure
   functions, routing decisions, configuration parsing, error mapping. No sockets.
2. **Integration** (`tests/integration/`) — AS and mock S-SBC on localhost UDP with
   ephemeral ports; assert that the INVITE the mock receives carries the translated
   Request-URI and number format.
3. **E2E** (`tests/e2e/`) — a complete call (`INVITE -> 100 -> 180 -> 200 OK -> ACK ->
   BYE`) plus the error branches: no matching rule -> `404`, policy rejection -> `603`,
   caller abandons -> `CANCEL`. Output a human-readable, Call-ID keyed trace usable as
   demo evidence.

Additional expectations:

- Test ports are configurable so parallel runs and CI never collide on UDP 5060.
- Acceptance items (`docs/acceptance/criteria.md`) are numbered and trace back to
  `REQ-*` identifiers; the report carries evidence per §4.8.
- **DoD for a milestone**: feature implemented, three layers green, `make lint` clean,
  README and the affected docs updated, console shows the new flow (from M3 on), new
  gaps registered, acceptance items for the milestone accepted with evidence, version
  bumped with a CHANGELOG entry and tag, and `make demo` still works from a clean
  checkout.

## 12. Coding Conventions

- **English everywhere**: identifiers, comments, log messages, error strings, docs,
  commit messages.
- Type hints on all public functions; `mypy` clean.
- Translation and routing logic is **pure and side-effect free** — no sockets, no global
  state, no clock access inside `routing/engine.py`.
- sippy interaction is confined to `sip_adapter.py` and `call_controller.py`; that glue
  stays thin so the rest of the code remains testable and readable.
- Correlate every log line and console event with the SIP **Call-ID**.
- Small reviewable functions; no premature abstraction and no abstraction added "because
  production would need it".
- Comments explain *why* (protocol decisions, trade-offs, ADR references); never restate
  code.

## 13. Git & Commit Rules

- **Conventional Commits**, English, one logical change per commit:
  `feat` · `fix` · `docs` · `refactor` · `test` · `chore` · `build`
- **Pre-commit gate (all green)**: `ruff format --check`, `ruff check`, `mypy`,
  `pytest` (all three layers).
- **Behaviour changes update the documentation chain**: requirement (`REQ-*`) → design
  (HLD/LLD) → interface specification and message samples → acceptance item →
  CHANGELOG. A behaviour change that does not walk this chain is incomplete.
- **Structural changes** (new/moved directory, new/renamed config field, changed run
  command or port, new service) must update `AGENT.md`, `README.md` and `docs/README.md`
  in the same commit.
- No commit may contain secrets, certificates, captures of real traffic or local env
  files.

## 14. Agent Collaboration Rules

Non-negotiable for AI agents (and a good default for humans):

1. **Never guess.** No invented SIP headers, status codes, parameters or sippy APIs. If
   the RFC, the sippy source, or the codebase does not tell you, **ask**.
2. **Ask when uncertain.** Ambiguity, missing information, or a decision with
   protocol/security impact -> stop and ask. Do not pick silently.
3. **No unconfirmed refactors.** Do not delete existing code, rewrite large files or
   restructure directories without an explicit, approved plan. Propose first.
4. **Change what was asked.** No drive-by refactors, no unrelated "improvements", no
   reformatting files you were not asked to touch.
5. **Update docs with structure.** New behaviour or structure without documentation
   updates is an incomplete task.
6. **Report honestly.** Do not claim passed tests, verified behaviour or working calls
   that were not executed. "I believe" is not evidence.
7. **Log the gaps.** Any shortcut taken for the sake of the POC goes into
   `docs/production-gaps.md` (§3), not into silence.
8. **Presentation is part of the task.** Naming, layout, documentation and evidence are
   deliverables, not afterthoughts (§4).
9. **Delegate execution to subagents.** The main agent must not perform coding, testing,
   or file editing itself. It plans, splits the work, and delegates each milestone (or
   work-stream within a milestone) to a subagent. The main agent reviews the subagent's
   output and reports back to the maintainer; it does not write the code.

### 14.1 How to delegate (team mode) — the single canonical how-to

The `Task` tool has two execution modes. Knowing the difference is mandatory, because a
wrong choice silently makes the subagent read-only and blocks the milestone:

- **Synchronous subagent** (no `name` argument, e.g. `code-explorer`): read-only. It has
  only search/read tools. Use it for exploration and investigation, **never** for code
  changes. This is the "read-only subagent" trap M0 hit.
- **Team mode** (`name` argument supplied): the spawned member runs detached in the
  background and **can edit files** — the only mode allowed to implement.

To spawn a writing member:

1. Call the `Task` tool with:
   - `name`: a short role label, e.g. `m3-dev`. Supplying `name` turns on team mode and
     auto-creates the team, so no separate `team_create` call is needed; use
     `team_create` only to pre-create a named team or to group several members, then pass
     its `team_name`.
   - `prompt`: the milestone brief. State the scope, the opening ritual (§15 handover
     protocol), the DoD (§16), and that the member owns the code, tests, docs and commit
     — **not** the tag: tagging is the maintainer's step (agents do not tag).
   - `mode`: `"acceptEdits"`. This auto-accepts the member's file edits so execution does
     not stall waiting for per-edit approval. (Use `"bypassPermissions"` only when shell
     commands need auto-approval too; otherwise prefer the narrower `"acceptEdits"`.)
   - `max_turns`: set high enough to finish the milestone, or omit.
2. Review the member's final message: verify DoD evidence, ask it to fix gaps, do **not**
   redo its work in the main agent.
3. (Optional) When the work is done, `shutdown_request` the member and `team_delete` the
   team once the milestone is committed (tagging is the maintainer's step; agents do not
   tag).

Rule of thumb: **read-only work -> synchronous subagent; any file change -> team mode with
`mode = "acceptEdits"`.** If a subagent reports it "cannot edit" or "is read-only", you
spawned it in the wrong mode — respawn it in team mode.

**Message timing and irreversibility (learned in M3).** A team-mode message is delivered to
the member's inbox and read only at its next turn boundary, so it **cannot interrupt a turn
that is already running**. A `stop` or correction sent while the member is mid-turn is seen
too late to prevent the work — in M3 a correction arrived after the member had already
implemented the change. Therefore: (a) put every hard constraint in the spawn `prompt`
itself, before the member starts, rather than trusting a later message to enforce it;
(b) instruct the member to stop and report **before** any change that is expensive to
revert (adding a dependency, changing a schema, deleting code, committing); (c) if a wrong
turn has already run, expect to revert the member's uncommitted work and have it re-do,
because the message that would have prevented it was never seen in time.

**Operating with the lag (main-agent practice).** Treat every message as asynchronous and
possibly late: (a) send decisions when the member is idle — it normally reports at the end
of a turn, so reply then; (b) expect a decision sent just after the member finished to be
read only on its next turn, so re-affirm and have it apply the change if it already produced
a result; (c) make corrections self-contained and mark them as superseding earlier
instructions, since a member may read a stale "hold" and a new decision in the same turn;
(d) when several decisions are pending, send one consolidated instruction rather than a
stream of small ones.

### 14.2 Delegation policy for the Post-M4 items (P1–P6)

Post-M4 work (tracked as P1–P6 in `docs/roadmap.md`) follows §14 rule 9: the main agent
plans, tracks status in `docs/roadmap.md` and reviews; it does not implement.

- **Main-agent boundary.** The main agent plans and tracks status (Open → In progress →
  Done) in `docs/roadmap.md`, and reviews the member's result. It does not implement, does
  not read source to design the implementation, and does not pre-design the change — that
  reasoning belongs to the member.
- **Implementation or any file change on a P-item -> team-mode member** (writable); spawn
  it per §14.1. Its write permission was verified on 2026-09-16.
- **Exploration/investigation -> synchronous subagent** (read-only, e.g. `code-explorer`).
  Never hand it a P-item that requires code or config changes.
- **How-to:** see §14.1 — the single canonical guide; it is not repeated here.

## 15. Roadmap

**Status board: `docs/roadmap.md`.** That file is the live record of scope, status,
handover notes and open items for each milestone. This section states the fixed scope
only; never edit milestone status here (and never duplicate milestone status here).

- **M0 — Foundation.** Telecom-grade skeleton: `config/ deploy/ src/ tests/ tools/`,
  `pyproject.toml` + `uv.lock`, ruff/mypy/pytest config, CI workflow, meta files
  (VERSION, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, NOTICE), `docs/`
  baseline (README index, SRS, HLD/LLD skeletons, ADR directory, specs index with
  message samples, deployment/runbook/troubleshooting skeletons, acceptance criteria,
  production gaps, demo script, glossary), sample routing data per §4.6, compose
  network with UDP ports, `.env.example`, README quickstart, and the sippy-on-Python-3.10
  verification. No call logic.
- **M1 — Signalling path.** AS boots on sippy, mock S-SBC sends INVITE, a full call
  completes (`100 -> 180 -> 200 -> ACK -> BYE`) with headers and SDP passed through;
  structured logging, counters, health endpoint and graceful shutdown in place. Console
  not yet connected.
- **M2 — Number translation.** Rule engine with YAML hot reload, Request-URI and number
  format rewriting inside `CallController`, error branches (`404`, `603`, `CANCEL`),
  error code system, unit + integration + e2e tests, first acceptance run.
- **M3 — Console.** Internal REST + WebSocket API, telecom-operations UI per §4.4, live
  message flow, payload viewer, rule-hit display, statistics dashboard, SVG topology.
- **M4 — Acceptance and polish.** Full acceptance run with evidence per §4.8, demo
  script rehearsal, ADR and documentation review, tagged release.

Milestones are delivered in order; each one ends with the DoD in §11 satisfied and a
tagged version.

### Handover protocol (one conversation per milestone)

**Opening ritual** — the first message of a milestone conversation names the milestone
and requires reading, in this order:

1. `AGENT.md` (this file) — rules and standards
2. `docs/README.md` — documentation map
3. `docs/roadmap.md` — the section for the current milestone: status, exit criteria,
   handover notes, open items
4. `docs/acceptance/criteria.md` — the acceptance items owned by that milestone

A milestone conversation may not change scope that belongs to another milestone. A scope
change is a maintainer decision, not a local edit.

**Closing ritual** — before a milestone conversation ends:

1. Run the DoD (§16) and record the result in `docs/acceptance/report.md` with evidence
   per §4.8
2. Update `docs/roadmap.md`: status, handover notes, open items and the entry state for
   the next milestone
3. Update `CHANGELOG.md` and `VERSION`, commit with the milestone scope prefix
   (`feat(m2): ...`). Do not create the tag: tagging `v<version>-m<n>` is the
   maintainer's step (agents do not tag)
4. Write down anything a fresh conversation would otherwise have to re-derive —
   conversation context is not a handover artefact

## 16. Definition of Done (checklist)

- [ ] Feature works end to end; `make demo` passes from a clean checkout
- [ ] Unit + integration + e2e tests added and green
- [ ] `ruff format`, `ruff check`, `mypy` clean
- [ ] Console reflects the new capability (from M3 onward)
- [ ] README and the affected documents updated (including any new env var, port or
      command)
- [ ] Requirement IDs, acceptance items and CHANGELOG updated for the behaviour change
- [ ] New POC shortcuts registered in `docs/production-gaps.md`
- [ ] `AGENT.md` and `docs/README.md` updated if anything structural changed
- [ ] Acceptance items for the milestone carried out with evidence per §4.8
- [ ] Version bumped (the tag `v<version>-m<n>` is the maintainer's step; agents do
      not tag)
- [ ] No secrets, certificates or real traffic captures committed
