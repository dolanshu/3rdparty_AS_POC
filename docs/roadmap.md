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
| M2 — Number translation | done (2026-09-16) | pending (tagging is done by the maintainer) |
| M3 — Console | done (2026-09-16) | pending (tagging is done by the maintainer) |
| M4 — Acceptance and polish | done (2026-09-16) | pending (tagging is done by the maintainer) |

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
- **`make demo` is a stub in M0** (it prints the rule set and the decisions).
  **Updated 2026-09-16 (M1):** the four e2e cases are no longer in
  `tests/e2e/test_call_flows_pending.py`; that file became `tests/e2e/test_call_flows.py`,
  where the complete call and the caller-abandonment case pass and the `404` / `603`
  branches stay skipped for M2.
  **Updated 2026-09-16 (post-M2 audit):** `make demo` now places a real call and narrates
  it (`tools/demo_call.py`); the rule table moved to `make rules`. `tools/capture_call.py`
  also gained a settle window, so a capture now always records the closing 200 OK instead
  of sometimes stopping at 13 samples.
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
- **`make demo` was still a stub at M1** (it printed the rule set). Resolved in the
  post-M2 audit: `make demo` now places a real call (`tools/demo_call.py`) and the rule
  table moved to `make rules`.
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

**Status:** done (2026-09-16); tagging is done by the maintainer.

**Scope:** rule engine with YAML hot reload; Request-URI and number format rewriting
inside `CallController`; error branches (`404`, `603`, `480`, `500`, `CANCEL`); error code
system; unit + integration + e2e tests; first acceptance run.

**Entry criteria:** M1 done; call flow stable — met.

**Exit criteria:**

- [x] Rules loaded from `config/` with hot reload
- [x] Translation applied to Request-URI and number formats (E.164, `0`-prefixed, short
      codes, international `00`)
- [x] Multiple next hops with priority and failover
- [x] Error branches `404` / `603` / `CANCEL` covered by tests
- [x] Error code system (`AS-*`) implemented and documented in the LLD
- [x] Unit, integration and e2e layers green

**Handover notes:**

- **Rule versioning:** the shipped `config/routing_rules.yaml` has `version: 1` and
  `name: sample-office-routing` (17 rules, 6 next hops). The `RuleSetStore` detects a
  file change by size + modification time and activates the new rule set; a broken edit
  keeps the previous rule set (ADR-0004 fail-safe reload). The AS polls for reload from a
  loop-owned timer (`RULE_RELOAD_POLL_SECONDS = 1.0`) so the sippy thread is never
  blocked by file I/O.
- **Hot reload verification:** `tests/integration/test_translation.py` covers both the
  successful reload (new rule set name active) and the fail-safe reload (broken YAML
  keeps the previous rule set and logs `AS-RULE-002`). The `_poll_rule_reload` method
  logs `rule set reloaded` with the new name and rule count.
- **Next-hop failover result:** the `CallController` owns a controller-managed no-answer
  timer (`_DEFAULT_NEXT_HOP_EXPIRE = 3.0` s) instead of sippy's `expire_time`, because
  sippy anchors `expire_time` to the INVITE event `rtime` and it would fire immediately
  on a failover attempt whose pending event carries the original timestamp. When the
  timer fires, the controller calls `uaO.disconnect()`, sippy emits a
  `CCEventDisconnect`, and `_relay_from_next_hop` treats it as a failover trigger when
  the leg has not connected. The failover test
  (`test_next_hop_failover_uses_the_second_hop`) proves a call completes via the second
  hop when the first is unreachable.
- **Translation seam:** `CallController.apply_call_policy` is the single place that
  rewrites the called number. It rebuilds the `CCEventTry` with the translated called
  number (data tuple index 2) and attaches pass-through headers. SDP still passes
  through verbatim (M1 rule, unchanged).
- **Error branches:** `404` / `AS-ROUTE-001` (no match, e.g. `+999...`), `603` /
  `AS-ROUTE-002` (rule `R-BLOCK-90` rejects premium-rate), `480` / `AS-ROUTE-003` (no
  next hop — defended by schema validation at load time, exercised at unit level),
  `500` / `AS-ROUTE-004` (translation yields empty — exercised at unit level), `CANCEL`
  (caller abandonment, e2e). The rejection is sent on the trunk leg by
  `uaA.recvEvent(CCEventFail((status, phrase, None)))`.
- **sippy facts discovered:** `CCEventTry` data is `(cId, callingID, calledID, body,
  auth, callingName)`; `UacStateIdle` builds `rTarget` from `rAddr0` (the UA's
  `nh_address`) and uses `calledID` as the Request-URI user part, so rebuilding the
  event with a new `calledID` rewrites the Request-URI. `UacStateTrying.recvEvent` on
  `CCEventFail` changes state to `UacStateCancelling` but does **not** enqueue the event
  for the callback, so the controller uses `disconnect()` (which enqueues
  `CCEventDisconnect`) to trigger failover. Stale UA events from a replaced `uaO` are
  ignored in `recv_event` (`if ua is not self.uaO: return`).

**Open items:**

- The `_DEFAULT_NEXT_HOP_EXPIRE = 3.0` no-answer timeout is a loopback POC value; a real
  deployment should make it per-next-hop or configuration-driven (e.g.
  `_next_hop_expire_seconds` in `global_config`).
- The `480` / `AS-ROUTE-003` branch is defended by `AS-RULE-003` schema validation at
  load time; it is exercised at the unit level but not end-to-end, because the schema
  rejects a rule that references an unknown next hop before runtime.
- The `500` / `AS-ROUTE-004` branch (translation yields empty) is exercised at the unit
  level (`test_translation_to_empty_yields_500`); a rule that strips the entire number
  is a misconfiguration that the loader accepts but the engine rejects at decision time.
- `deploy/docker-compose.yml` still has `ALLOWED_PEERS: s-sbc-mock,127.0.0.1`; container
  addresses are not knowable in advance (carried from M1).

**Entry state for M3:** M2 is done; the AS applies number translation, handles error
branches, and supports hot reload and next-hop failover. The internal API
(`InternalApiServer`) already serves `/healthz`, `/api/v1/metrics` and
`/api/v1/traces`; M3 builds the FastAPI application and the console UI on top.

## M3 — Console

**Status:** done (2026-09-16) — all four exit criteria met, gates green, two acceptance
items executed with evidence in `docs/acceptance/report.md`. Tagging is the maintainer's
step (agents do not tag).

**Scope:** internal REST + WebSocket API; telecom-operations UI per `AGENT.md` §4.4; live
message flow; payload viewer; rule-hit display; statistics dashboard; SVG topology.

**Entry criteria:** M2 done; counters and trace already exposed by the AS — met.

**Exit criteria:**

- [x] Internal API serves call trace, rules, configuration and statistics
- [x] UI meets `AGENT.md` §4.4 (dark console theme, status bar, navigation, live flow,
      rule highlight, statistics, SVG topology)
- [x] No third-party front-end libraries
- [x] Console runs as a separate process (per ADR-0002)

**Done in this conversation (2026-09-16):**

- `src/as_app/internal_api.py` — rewritten from the M1 `http.server` scaffolding to a
  FastAPI application served by uvicorn on a daemon thread (ADR-0002, AGENT.md §6). The app
  factory (`create_internal_api_app`) closes over the existing registries (`MetricsRegistry`,
  `TraceRecorder`, `RuleSetStore`) so every route handler is a thin read of a lock-guarded
  snapshot. New endpoints beyond the M1 baseline: `GET /api/v1/rules` (read-only active rule
  set), `GET /api/v1/traces/{call_id}` (one call), `WS /ws/events` (live event feed). The
  payload builders (`health_payload`, `metrics_payload`, `rules_payload`, `trace_payload`,
  `traces_payload`) remain pure functions, unchanged from M0/M1, so the unit tests that cover
  them still pass.
- `src/console/main.py` — full operations console UI: dark theme (§4.4), top status bar
  (peer state, version, uptime, call counters, WebSocket indicator), left navigation (Call
  Trace / Rules / Configuration / Statistics / About), live message flow with direction
  colour coding and rule-hit highlighting, Call-ID filter, expandable payload viewer, SVG
  topology (S-SBC <-> AS <-> Next-Hop with animated call path), statistics dashboard with
  stat cards and bar charts, rules table with next hops, configuration view. All CSS inline
  in `<style>`, all JS inline in `<script>` — no external `<script src>` or `<link href>`
  (REQ-NF-010). Fixed a missing `if __name__ == "__main__"` guard so `python -m console.main`
  now works. The page injects the AS API URL at request time via a `__AS_API_URL__` token.
- `pyproject.toml` — version bumped to `0.4.0`; `fastapi` + `uvicorn[standard]` added to the
  `as` optional-dependency group (the internal API imports them at runtime) in addition to
  the existing `console` group. The `dev` dependency group already had them for test parity.
- `uv.lock` — regenerated by `uv lock`.
- `tests/integration/test_console.py` — 5 new tests: ACC-M3-001 (page has no third-party
  libraries; page has all four §4.4 UI surfaces; AS API URL injection) and ACC-M3-002
  (internal API serves health, metrics, rules, traces; console runs as a separate process
  with no external refs in the served page).
- `AGENT.md` §14 — added rule 9 (delegate execution to subagents) and §14.1 (how to
  delegate via team mode), written during this milestone conversation.

**Handover notes (read this before starting M4):**

- **Framework is ADR-mandated, not a guess.** ADR-0002 line 11 names FastAPI + uvicorn;
  `AGENT.md` §6 line 260 pins it. The M1 `InternalApiServer` scaffolding (`http.server`)
  was a temporary stand-in explicitly documented as "scaffolding for the FastAPI application
  of M3" — M3 replaced it, not refactored it.
- **ED2/sippy-thread constraint (ADR-0002 consequences, line 44-45).** The AS process is
  single-threaded: `ED2.loop()` blocks the main thread and `AGENT.md` §6 forbids sharing it
  or an asyncio loop with anything else. The internal API is served by uvicorn on a daemon
  thread with its own asyncio loop. `uvicorn.Server` does not install signal handlers on
  non-main threads, so the AS owns `SIGTERM` handling and calls `server.should_exit = True`
  to stop the API. Every route handler only reads lock-guarded snapshots from the existing
  `MetricsRegistry`, `TraceRecorder` and `RuleSetStore` — it never calls into the sippy
  stack, and never blocks. A future conversation that moves the API into the sippy thread
  would violate this constraint; do not do it.
- **WebSocket feed is poll-based, not pub/sub.** `WS /ws/events` polls the `TraceRecorder`
  (a passive store) at a fixed 1-second interval and pushes new call traces as JSON batches.
  This is a POC simplification — see `docs/production-gaps.md` — but it means the console
  sees new calls within 1 s of their first event without any
  pub/sub plumbing.
- **Console UI is a single inline HTML string.** The entire page (CSS + JS + HTML) lives in
  `CONSOLE_PAGE` in `src/console/main.py`. This is deliberate: no build step, no third-party
  libraries (§4.4, §6). The JS is minified-in-spirit (short variable names, no comments) to
  keep it manageable. If the page grows significantly, consider splitting it into
  `src/console/static/` files served by FastAPI's `StaticFiles` mount — but only if the
  single-file approach becomes unwieldy.
- **CORS is open (`allow_origins=["*"]`).** The console is a separate process on a different
  port, the API is loopback-only, and it is a demo surface (ADR-0002, gaps accepted). The
  console's browser-side JS fetches directly from the AS API URL.
- **Console process version is `"0.1.0"`.** `src/console/main.py` `create_app` hardcodes
  `version="0.1.0"` for the console's own health endpoint. This is the console component
  version, not the AS version — the AS version comes from `VERSION` and is served on the AS
  health endpoint. They are independent processes with independent versions.

**Open items:**

- The WebSocket event feed is poll-based (1 s interval) rather than event-driven. A
  production console would use a pub/sub model where the `TraceRecorder` pushes events as
  they are recorded. Registered in `docs/production-gaps.md`.
- The console has not been exercised against a live call with the browser open (the
  integration test starts the console process and fetches the page, but does not drive a
  browser). This is a manual-verification gap for M4 or the maintainer.
- `deploy/docker-compose.yml` still has `ALLOWED_PEERS: s-sbc-mock,127.0.0.1` (carried from
  M1). Container addresses are not knowable in advance, so the console's browser-side JS
  would reach the AS at `http://as:8080` inside the compose network but the AS would reject
  SIP INVITEs from the mock. This does not affect the console — only the SIP path.

**Entry state for M4:** M3 is done; the console runs as a separate process serving the
operations UI, and the AS internal API serves health, metrics, rules, traces and a live
WebSocket event feed. M4 runs the full acceptance review with evidence per `AGENT.md` §4.8,
rehearses the demo script, and reviews all documentation for staleness. Nothing in the
signalling path or the console needs to change for M4.

## M4 — Acceptance and polish

**Status:** done (2026-09-16) — all exit criteria met except the tag itself, which is the
maintainer's step (agents do not tag), exactly as for M0–M3.

**Scope:** full acceptance run with evidence per `AGENT.md` §4.8; demo script rehearsal;
ADR and documentation review; tagged release.

**Entry criteria:** M3 done — met.

**Exit criteria:**

- [x] Every acceptance item executed with the four kinds of evidence
- [x] `docs/demo-script.md` rehearsed end to end
- [x] Documentation review pass: no stale samples, no broken links, no unregistered gaps
- [x] Version prepared and release notes published; **the tag itself is pending the
      maintainer** (`v0.5.0-m4`)

**Done in this conversation (2026-09-16):**

- Full acceptance run recorded in `docs/acceptance/report.md` (M4 section): ACC-M4-001
  (every acceptance item carries the four kinds of evidence) and ACC-M4-002
  (`docs/demo-script.md` rehearsed end to end) both accepted.
- Demo rehearsal with real output: `make demo` (exit 0), `make probe` (exit 0),
  `make rules` (exit 0), `make capture` (14 samples), the three failure branches
  (`+9991234567` → `404` / `AS-ROUTE-001`; `+861681234567` → `603` / `AS-ROUTE-002`;
  `pytest tests/e2e -m e2e -k cancel` → 1 passed) and the console (`make dev` + `make mock`
  + `make console`: `/healthz` ok, the call visible in the AS internal API, console page
  HTTP 200).
- Documentation review and correction of stale milestone status in
  `docs/demo-script.md` (console section now live; the `404` example number was wrong),
  `AGENT.md` §15 (removed the stale "current phase: M0" line),
  `docs/requirements/functional-and-nonfunctional.md` (status column corrected to `done`),
  `docs/README.md`, `docs/architecture/hld.md`, `docs/architecture/lld.md`, ADR-0002,
  `docs/operations/deployment.md`, `docs/operations/runbook.md` and
  `docs/specs/message-samples/README.md`.
- Release preparation: `VERSION` → `0.5.0`; `CHANGELOG.md` `0.5.0` release notes (the
  `[Unreleased]` content folded in).

**Handover notes (for the maintainer):**

- **Tagging.** The release is prepared but not tagged (agents do not tag). The maintainer
  should create the annotated tag `v0.5.0-m4`.
- **Known test flake (not fixed, out of M4 scope).** `tests/integration/test_translation.py`
  `::test_next_hop_failover_uses_the_second_hop` failed in roughly 1 run in 6 with
  `TypeError: 'NoneType' object is not subscriptable` in sippy's
  `SipTransactionManager.transmitData`. Root cause: `SipTransactionManager.shutdown()`
  nulls `global_config` but leaves a pending `timerA` retransmission scheduled, and `ED2` is
  a process-wide singleton, so the stale timer fires during a later test. The failover test
  (which points a hop at an unbound port on purpose) is the natural trigger. Five
  consecutive full-suite reruns were green (118 passed). A fix belongs to the M2 test code.
- **Version drift (defect, reported, not changed in M4).** `src/as_app/__init__.py`
  hardcodes `__version__ = "0.1.0"`, so the AS `/healthz` and its startup log report
  `0.1.0` even though `VERSION` is now `0.5.0`. The `VERSION` ↔ `pyproject.toml` pair is
  guarded by a baseline test; `as_app.__version__` is not. See the M4 report open items.

**Open items:**

- **Version drift in `as_app.__version__`** (above): derive it from `VERSION`, or register
  it as an accepted gap. Reported in M4; not changed because M4 must not touch `src/`.
- **`deploy/docker-compose.yml` keeps `ALLOWED_PEERS: s-sbc-mock,127.0.0.1`** (carried from
  M1): container addresses are not knowable in advance, so the mock's SIP INVITEs are
  rejected in compose. Compose is validated with `docker compose config` only, never run to
  a call.
- **Console not browser-verified against a live call** (carried from M3; registered in
  `docs/production-gaps.md`).
- **`AGENT.md` §4.7 names a "release notes template"** that does not exist as a separate
  file; the per-version `CHANGELOG.md` nodes serve that purpose. Maintainer to confirm the
  CHANGELOG counts as the template, or drop the wording.

**Entry state for the next milestone:** M4 is the final milestone — there is no M5. A future
iteration starts from the open items above and from `docs/production-gaps.md`.

## Conventions

- **Single source of truth:** rules live in `AGENT.md`; live status lives here; evidence
  lives in `docs/acceptance/report.md`
- **Commit scope:** `feat(m2): ...`, `fix(m1): ...`, `feat(m3): ...`
- **Version and tag:** one version node per milestone, tag `v<version>-m<n>`
- **Decisions:** recorded as ADRs in `docs/architecture/adr/`, referenced from code
