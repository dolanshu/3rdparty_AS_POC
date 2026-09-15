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
| M1 — Signalling path | done (2026-09-16) | pending (tagging is done by the maintainer) |
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
- **`make demo` is a stub** in M0: it prints the rule set and the decisions. It is still a
  stub after M1 (see the M1 open items). **Updated 2026-09-16 (M1):** the four e2e cases
  are no longer in `tests/e2e/test_call_flows_pending.py`; that file became
  `tests/e2e/test_call_flows.py`, where the complete call and the caller-abandonment case
  pass and the `404` / `603` branches stay skipped for M2.
- The default catch-all rule `R-DEFAULT-99` is present but **disabled** so that the
  no-match `404` branch stays demonstrable. Enable it to route every remaining number.

**Open items:**

- **Resolved (maintainer, 2026-09-16): `src/as_app/observability/logging.py` keeps its
  name.** Ruled on after M0 flagged that it shadows the stdlib `logging` module. The
  binding rule is now in `AGENT.md` §5: all imports of it are package-absolute, and
  `src/as_app/observability/` is never put on `sys.path`. M1 must respect this; the trap
  itself is documented in `docs/architecture/lld.md` section 8.
- **The configuration model lives in `bootstrap.py`** (startup parsing is a startup
  concern). Still open after M1 (the model did not grow): if it grows later, move it to
  its own module and update `AGENT.md` §5 — recorded in `docs/architecture/lld.md`
  section 1.1.
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

**Status:** done (2026-09-16) — all six exit criteria met, gates green, six acceptance
items executed with evidence in `docs/acceptance/report.md`. Tagging is the maintainer's
step (agents do not tag).

**Scope:** AS boots on sippy; mock S-SBC sends INVITE; a full call completes
(`100 -> 180 -> 200 -> ACK -> BYE`) with headers and SDP passed through; structured
logging, counters, health endpoint and graceful shutdown in place. Console not yet
connected.

**Entry criteria:** M0 done; `uv sync` works; sippy verified.

**Exit criteria:**

- [x] AS process starts, binds UDP, and answers an INVITE from the mock
- [x] Complete call flow including BYE, verified by e2e test
- [x] Headers and SDP pass through unmodified (asserted in integration tests)
- [x] Structured logging with Call-ID correlation
- [x] Counters exposed; health endpoint live; `SIGTERM` shuts down gracefully
- [x] Acceptance items for M1 recorded with evidence

**Done in this conversation (2026-09-16):**

- `src/as_app/call_controller.py` — the real B2BUA glue. `CallController` owns `uaA`
  (trunk leg) and `uaO` (next-hop leg) and relays sippy call control events between them;
  `TrunkCallMap` is the process-wide trunk entry point and enforces the peer allowlist.
  `CallController.apply_call_policy()` is the **single documented seam** where number
  translation is inserted in M2 — in M1 it relays the call verbatim and logs
  `call relayed without translation`.
- `src/as_app/main.py` — `AsStack` wires `SipConf` + `SipTransactionManager` +
  `ED2.loop()`, starts the internal API and stops the loop from a loop-owned timer when a
  signal handler has requested shutdown.
- `src/as_app/internal_api.py` — `InternalApiServer`: a standard-library HTTP server on
  its own daemon thread serving `/healthz`, `/api/v1/metrics` and `/api/v1/traces` from
  the existing payload builders. It is scaffolding for the FastAPI application of M3, not
  a web framework.
- `src/as_app/observability/tracing.py` — `SipMessageRecorder` records the verbatim SIP
  messages sippy writes, which is what makes message samples captured rather than
  hand-written.
- `src/s_sbc_mock/{uac,uas,main}.py` — the mock S-SBC is implemented: the UAC side places
  a call with an ISC-flavoured INVITE (`P-Asserted-Identity`, `P-Charging-Vector`,
  `P-Visited-Network-ID`, `Privacy`, `Subject`, `Organization`, `Priority` and an SDP
  offer), the UAS side answers `180` / `200 OK` and releases with `BYE`. It runs as its
  own process and as a test fixture.
- `tools/capture_call.py` — captures the messages of a real call into
  `docs/specs/message-samples/` (14 files, `01-in-invite-trunk.txt` …
  `14-in-200-trunk.txt`).
- Tests: `tests/e2e/test_call_flows.py` replaces `test_call_flows_pending.py`
  (complete call and caller abandonment pass; the `404` / `603` branches stay declared and
  skipped for M2), `tests/integration/test_signalling_path.py` covers pass-through, the
  peer allowlist and the process lifecycle, and `tests/conftest.py` grew a `TrunkPair`
  fixture that binds AS and mock on ephemeral ports and drives the shared sippy loop.

**Handover notes (read this before starting M2):**

- **Ports used.** Nothing hardcodes `5060`. The AS uses `SIP_LISTEN_PORT` (default 5060),
  `SBC_PEER_ADDRESS`/`SBC_PEER_PORT` for the next hop, `INTERNAL_API_PORT` for health and
  counters. The mock uses `--listen-port` for its core (UAS) side and `--trunk-port` for
  its trunk (UAC) side, which defaults to `listen-port - 1` — that is why compose exposes
  `15060/udp` and `15061/udp`. Tests allocate every port dynamically
  (`tests/conftest.py::_free_udp_port`).
- **`ED2` is a process-wide singleton and `ED2.loop()` must run on the main thread.** In
  production the AS and the mock are separate processes, so this never shows up. In the
  tests they share one interpreter, so they share one loop: `TrunkPair.run_until()`
  drives it and the test asserts afterwards. Do not start a second `ED2.loop()`.
- **`SipConf` is a process-wide singleton too** (`my_address`, `my_port`, `my_uaname`) and
  sippy reads it while it builds a `Via` and a default `Contact`. The mock deliberately
  does not write to it; each side pins its own identity around the messages it generates
  (`_as_sip_identity` in `call_controller.py`, `_trunk_identity` in `uac.py`) and sets
  `ua.lContact` and `ua.local_ua` explicitly. If you add a third sippy application, follow
  the same pattern or messages will carry the wrong `Via`.
- **A side needs its own `SipTransactionManager` when it needs its own local port**, and
  each manager needs `global_config['_sip_tm']` set right after construction.
- **sippy facts discovered (all by running it):**
  - `100 Trying` is emitted by `UasStateIdle` when the INVITE is terminated; a UAS
    application does not send it.
  - `CCEventTry` carries `(call-id, calling, called, body, auth, calling-name)`; the
    outbound Request-URI is built from `rAddr0` (the next hop) in `UacStateIdle`, and
    `event.onUacSetupComplete(ua)` is the documented hook for changing it.
  - Extra headers are carried on the event (`CCEventGeneric.extra_headers`) and appended
    to the generated request — that is how the pass-through headers reach the second leg.
  - The `ACK` of a `200 OK` is sent by the transaction layer and never raises a call
    control event, so it does **not** appear in the Call-ID keyed trace. It is in the
    message samples.
  - `SipGenericHF.getCanName()` only capitalises the first letter, so
    `P-Charging-Vector` leaves the AS as `P-charging-vector`.
  - `SipTransactionManager.shutdown()` releases the UDP sockets; call it before a test
    ends or the next run cannot bind the same port.
- **`make demo` is still a stub.** It prints the rule set; the call demo is M2/M4 work.
  `tools/capture_call.py` is the closest thing to a demonstrable call today.

**Open items:**

- **Scope conflict with the M1 task description (reported, not resolved).** The M1 brief
  asked for four un-skipped e2e cases. `AGENT.md` section 15 puts the `404` and `603`
  error branches in **M2 — Number translation**, and section 14.3 forbids a milestone
  conversation from taking scope from another milestone. M1 therefore delivers the
  complete call and the caller-abandonment (`CANCEL`) case, and leaves
  `test_unmatched_number_is_answered_with_404` and `test_blocked_number_is_answered_with_603`
  skipped with an explicit M2 reason. **Maintainer decision needed** if they should be
  pulled into M1.
- **`ALLOWED_PEERS` in `deploy/docker-compose.yml` still contains a service name**
  (`s-sbc-mock,127.0.0.1`). Container addresses are assigned at run time, so a name can
  never match the source address seen on the wire and every trunk INVITE would be
  answered `403`. M1 validated the stack with `docker compose config` only — no image was
  built and no container was started here. Fix options for the maintainer: give the mock a
  static address with an `ipam` block, or resolve peer names to addresses at start-up.
- **`SIP_LISTEN_ADDRESS: 0.0.0.0` in compose** makes sippy put `Via: SIP/2.0/UDP
  0.0.0.0:5060` on outbound messages, because `SipConf.my_address` is taken from the
  listen address. Harmless on loopback with `rport`, wrong for anything else.
- **The internal API is scaffolding.** `InternalApiServer` serves three read-only
  endpoints with `http.server`; M3 replaces it with the FastAPI application of ADR-0002.
- **The `ACK` is missing from the Call-ID keyed trace** (see the sippy facts above). If
  the console of M3 must show it, the trace has to be fed from the message recorder
  instead of from the call control events.

**Entry state for M2:** the complete call runs over real UDP in-process and as two
processes, headers and SDP pass through unchanged, the peer allowlist rejects unlisted
sources, the health endpoint and counters answer, and `SIGTERM` shuts the AS down cleanly.
M2 replaces the body of `CallController.apply_call_policy()` with the routing decision
(`as_app.routing.engine.decide`), rewrites the Request-URI and the number format, and adds
the `404`, `603` and `CANCEL` error branches — nothing else in the signalling path has to
change.

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
