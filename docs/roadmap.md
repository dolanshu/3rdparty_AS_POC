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
| M0 — Foundation | done (2026-09-16) | maintainer-owned |
| M1 — Signalling path | done (2026-09-16) | maintainer-owned |
| M2 — Number translation | done (2026-09-16) | maintainer-owned |
| M3 — Console | done (2026-09-16) | maintainer-owned |
| M4 — Acceptance and polish | done (2026-09-16) | maintainer-owned |

**Tagging (2026-09-16).** Milestone tags are the maintainer's step (agents do not tag).
The maintainer has created some milestone tags in their clone; the **remaining tags are
deferred — do not create them for now**. At write time this checkout carried no tags, so
verify a tag against the maintainer's clone before assuming it exists.

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
- **CI (planned via GitHub Actions, on hold) — RESOLVED by P3 (2026-09-17).** The workflow
  (`.github/workflows/ci.yml`) is committed and has now run on a runner: run
  [35155542999](https://github.com/dolanshu/3rdparty_AS_POC/actions/runs/35155542999),
  reported green by the maintainer across all five layers. The `AGENT.md` §4.8 CI-result
  evidence and the README CI badge are therefore no longer pending — see the P3 entry under
  "Next steps" and the P3 section of `docs/acceptance/report.md`. *(Original entry: the
  workflow's commands were executed locally because there was no CI runner in this
  environment; it was held by maintainer decision on 2026-09-16 — since lifted.)*
- **`uv` needs a package index mirror on this machine** (`UV_DEFAULT_INDEX=...`); the
  committed lock refers to the public PyPI, so this is local-only. Verified working
  (2026-09-16): `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple` plus
  `UV_PYTHON_DOWNLOAD_URL=https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download`
  install Python 3.10 + all deps in seconds. **Caveat:** syncing with a mirror rewrites
  `uv.lock` to point at the mirror — `git checkout uv.lock` before committing so CI keeps
  using public PyPI. Docker Hub is slow too; the compose demo needs a registry mirror
  (`https://docker.m.daocloud.io`) in `/etc/docker/daemon.json` (verified reachable here,
  but Docker is not installed in this environment so it was not run to a build).
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
  error branches in **M2 — Number translation**, and the `AGENT.md` §15 handover
  protocol forbids a milestone conversation from taking scope from another milestone.
  M1 therefore delivers the complete call and the caller-abandonment (`CANCEL`) case, and
  leaves `test_unmatched_number_is_answered_with_404` and
  `test_blocked_number_is_answered_with_603` skipped with an explicit M2 reason. **Maintainer decision needed** if they should be
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
  version, not the AS version. The AS version is derived from `VERSION` and served on the AS
  health endpoint (`src/as_app/__init__.py`; corrected in M4 — before that fix it was a
  hardcoded string that had drifted). They are independent processes with independent
  versions.

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
- Version-drift fix (maintainer-authorised, Option A): `src/as_app/__init__.py` now derives
  `__version__` from the `VERSION` file, and
  `tests/unit/test_repository_baseline.py::test_runtime_version_matches_the_version_file`
  asserts the two agree; `/healthz` and the startup log now report `0.5.0` (equal to
  `VERSION`). The suite is 119 passed after the change.
- Release preparation: `VERSION` → `0.5.0`; `CHANGELOG.md` `0.5.0` release notes (the
  `[Unreleased]` content folded in).

**Handover notes (for the maintainer):**

- **Tagging.** The release is prepared but not tagged (agents do not tag). The maintainer
  should create the annotated tag `v0.5.0-m4`.
- **Known test flake — registered and DEFERRED (not fixed in M4).**
  `tests/integration/test_translation.py::test_next_hop_failover_uses_the_second_hop` fails
  in roughly 1 run in 6 with `TypeError: 'NoneType' object is not subscriptable` in sippy's
  `SipTransactionManager.transmitData`. Root cause: `SipTransactionManager.shutdown()`
  cancels `cp_timer` but not the per-transaction retransmission timers (`t.teA`), so a
  pending `timerA` can dereference the now-`None` `global_config`; the in-process tests share
  one process-wide `ED2` loop, so a stale timer from a stopped manager fires during a later
  test. The failover test (which points a hop at an unbound port on purpose) is the natural
  trigger. Five consecutive full-suite reruns were green (118 passed before the version fix,
  119 after). Registered in `docs/production-gaps.md` ("Closing a transaction manager
  mid-retransmission"); the fix is deferred to a separate conversation after M4, at the
  maintainer's instruction.
- **Version handling — FIXED in M4.** `src/as_app/__init__.py` used to hardcode
  `__version__ = "0.1.0"`, so `/healthz` and the startup log served a stale version while
  `VERSION` advanced. It now derives `__version__` from the repository `VERSION` file, and
  `test_runtime_version_matches_the_version_file` guards the pair. The "an installed wheel
  does not carry `VERSION`" caveat is registered in `docs/production-gaps.md`.

**Open items:**

- **Version handling in `as_app.__version__`** (above): RESOLVED in M4 — derived from
  `VERSION` and guarded by a test. Only the wheel follow-up remains, registered in
  `docs/production-gaps.md`.
- **Docker compose demo was the largest open delivery gap — CLOSED by P1 (2026-09-16).**
  The compose network (static `ipam` subnet, `SIP_LISTEN_ADDRESS: 172.28.0.2`,
  `SBC_PEER_ADDRESS: 172.28.0.3`, `ALLOWED_PEERS: 172.28.0.3`) and the three images are now
  actually built and run: the stack completes a full call and the outbound `Via` carries
  `172.28.0.2:5060`, never `0.0.0.0`. See the P1 entry under "Next steps" for the changes and
  the Call-ID keyed evidence.
- **Console not browser-verified against a live call** (carried from M3; registered in
  `docs/production-gaps.md`).
- **`AGENT.md` §4.7 "release notes template" — RESOLVED in M4.** The maintainer chose to drop
  the wording; the phrase was removed from §4.7 and the per-version `CHANGELOG.md` nodes are
  the release notes. No separate template file exists or is required.

**Entry state for the next milestone:** M4 is the final milestone — there is no M5. A future
iteration starts from the open items above and from `docs/production-gaps.md`.

## Next steps (after M4) — tracked as P1–P7

These are not a formal M5 — `AGENT.md` §15 still names M4 as the final milestone — but they
are the known work to schedule, referenced as **P1–P7** (Post-M4 items) to stay distinct from
the M0–M4 milestones. Nothing here changes the M0–M4 scope that is already done.

- **P1 — Docker compose demo (top priority).** Make the three-service stack actually complete a
  call: fix `ALLOWED_PEERS` (give the mock a static `ipam` address, or resolve peer names to
  addresses at start-up so the on-wire source matches), fix `SIP_LISTEN_ADDRESS` so the
  outbound `Via` is not `0.0.0.0`, build the images and run `docker compose up` to a full
  `INVITE -> 200 OK -> BYE`. This closes the largest open delivery gap (see M4 open items).
  **[Required · Status: Done]** (2026-09-16)

  **Done in this conversation (2026-09-16).** The three images were built and the stack ran a
  complete call for the first time. Running it surfaced three defects that no amount of
  `docker compose config` could have shown; all three are fixed in `deploy/` and `config/`
  and nothing under `src/` changed:

  1. **The container command ran the wrong interpreter.** `uv sync` installs into the project
     environment `/app/.venv`, but `CMD ["python", ...]` resolved to the *system* interpreter,
     so all three services died with `ModuleNotFoundError: No module named 'sippy'`
     (and `... 'fastapi'`). `/app/.venv/bin` is now first on `PATH` in each Dockerfile.
  2. **The build could not reach its packages.** `uv sync --frozen` installs the wheel URLs
     recorded in `uv.lock` (`files.pythonhosted.org`) and does **not** substitute the
     configured index for them — verified with uv 0.12.15, see `docs/operations/deployment.md`
     §4.2. On this machine that host delivers ≈15 kB/s (a 10 MB wheel times out), so the build
     failed on uv's 30 s HTTP timeout. The package index is now a build arg whose **default is
     public PyPI** (CI unchanged); a build that overrides it lets uv re-resolve against that
     index inside the image only — same 50 packages, same pinned versions, and the committed
     `uv.lock` still references public PyPI.
  3. **The next hop was unreachable.** The AS originates the second leg to the hop the *rule
     set* selects, and the canonical `config/routing_rules.yaml` points every hop at
     `127.0.0.1` (correct for local runs, but each container has its own loopback).
     `SBC_PEER_ADDRESS` describes the peer for the startup self-check and logging; it does not
     rewrite the rule catalogue. The compose stack therefore uses
     `config/routing_rules.compose.yaml`, the same 17 rules with the hops at the mock's fixed
     trunk address `172.28.0.3` (see §4.2 of the deployment guide and the gap register).

  **Evidence (real, captured from the running stack).**
  `docker compose -f deploy/docker-compose.yml up -d` brings all three services up
  (`as` → 5060/udp + 8080/tcp, `s-sbc-mock` → 15060-15061/udp, `console` → 8081/tcp). The
  mock's default `office-to-mobile` call (`+86216180001` → `+8613800138000`) completed with
  **Call-ID `e48cb46795675ab0f76f5578cf5b4449`**; the AS structured log carries, in order:
  `invite received on the trunk` (`+8613800138000`), `routing decision taken` (`R-MOB-CM-40`),
  `call translated` (`+8613800138000` → `013800138000`, `national`),
  `invite originated towards the next hop` (`s-sbc-primary`), `call finished`
  (`disposition: completed`) — all with that Call-ID. On the wire the core leg carried
  `INVITE sip:013800138000@172.28.0.3:15061` with `Via: SIP/2.0/UDP 172.28.0.2:5060;rport`
  (never `0.0.0.0`), and the mock log shows the full
  `INVITE → 100 Trying → 180 Ringing → 200 OK → ACK → BYE → 200 OK` exchange on both legs.
  *(At the P1 run the core leg carried the same Call-ID; since the 2026-09-19 fix the
  outbound leg carries its own, `<trunk>-b2b_1` — see the post-fix re-test in
  `docs/acceptance/report.md`.)* The console answered `GET http://127.0.0.1:8081/healthz` with
  `{"status":"ok","component":"console"}` and served its page (HTTP 200, 16754 bytes); the AS
  internal API answered `GET :8080/healthz` (`{"status":"ok","version":"0.5.0",...}`),
  `GET :8080/api/v1/metrics` (`calls_total: 1`, `calls_by_disposition: {"completed": 1}`,
  `rule_hits: {"R-MOB-CM-40": 1}`, both peers `reachable`) and
  `GET :8080/api/v1/traces/e48cb46795675ab0f76f5578cf5b4449` (the Call-ID keyed trace).
  `docker compose down` then removed every container and the `as-poc-trunk` network: no stray
  container, network or volume was left behind.
- **P2 — Manual testing gate (after P1).** *Added by maintainer.* Before any further Post-M4
  work, the running stack must be verified by hand: (a) `as` / `s-sbc-mock` / `console` all
  healthy via `docker ps`; (b) a full `INVITE -> 180 -> 200 OK -> BYE` loop is observable in
  the AS logs; (c) the AS structured log shows the translated Request-URI and the matched rule
  name; (d) the console at `localhost:8081` renders the live message flow; (e) failure branches
  (`+999...` -> `404`, premium -> `603`) also behave correctly in the live stack. Human
  sign-off, not an automated check. **[Required · Status: Done]** (2026-09-16)

  **The human sign-off was performed by the maintainer on 2026-09-16.** P2 is a human gate
  and the sign-off is the maintainer's; no agent performed or can perform it. The run below is
  the machine evidence gathered for that review, and it covers item **(e)**, which was still
  open after P1.

  **Evidence (real, captured from the live stack on 2026-09-17).** The stack was brought up
  with the documented P1 recipe (`docker compose -f deploy/docker-compose.yml up -d`; the
  images from P1 were still cached, so no rebuild was needed).

  - **(a)** `docker ps`: `third-party-as-poc-as-1` (5060/udp + 8080/tcp),
    `third-party-as-poc-s-sbc-mock-1` (15060-15061/udp) and `third-party-as-poc-console-1`
    (8081/tcp) all `Up`.
  - **(b)+(c)** Success call `+86216180001` -> `+8613800138000`, Call-ID
    **`6d415fc865955c05162309eadd9416a5`**. The AS structured log carries, in order:
    `invite received on the trunk` -> `routing decision taken` (`rule_id: R-MOB-CM-40`) ->
    `call translated` (`+8613800138000` -> `013800138000`, `national`) ->
    `invite originated towards the next hop` (`s-sbc-primary`) -> `100 Trying` ->
    `180 Ringing` -> `200 OK` -> `call released … BYE` -> `call finished`
    (`disposition: completed`). The translated Request-URI is on the wire at the mock:
    `core side received INVITE call_id=6d415fc865955c05162309eadd9416a5
    ruri=sip:013800138000@172.28.0.3:15061`. An earlier run of the same stack at the
    documented `LOG_LEVEL: INFO` produced the same decision and translation for Call-ID
    `f55124fe232caaad5260f4504c0a2a5f`.
  - **(d)** `GET http://127.0.0.1:8081/healthz` -> `{"status":"ok","component":"console"}`,
    `GET http://127.0.0.1:8081/` -> HTTP 200, 16754 bytes, title `3rd-party AS Console`,
    0 external `<script src>` / `<link href>` references, AS API URL `http://as:8080`
    injected. The console container reaches the live feed it renders:
    `http://as:8080/api/v1/traces` -> HTTP 200, 3 calls. The maintainer viewed the live
    message flow at `localhost:8081` in a browser as part of their sign-off; no agent drove a
    browser, and browser-driven verification is still P4.
  - **(e)** Both failure branches were exercised **for real** in the live stack, each with an
    extra mock invocation (`docker compose run -d --name … s-sbc-mock python -m
    s_sbc_mock.main … --call CALLER=CALLED`, after `docker compose stop s-sbc-mock` freed the
    fixed trunk address `172.28.0.3` that `ALLOWED_PEERS` names):
    - `+9991234567` -> **`404`**, Call-ID **`fff8f9d4d34122326a6f7ffe8f157959`**:
      `routing decision taken` (`disposition: no_match`, `rule_id: ""`) and
      `call rejected by routing policy` (`method: 404`, `error_code: AS-ROUTE-001`,
      `error_detail: no routing rule matched the called number`). The mock saw
      `SIP/2.0 404 Not Found` on the trunk.
    - `+861681234567` -> **`603`**, Call-ID **`cd3b2b396d1e7a29074f119ee6d1b318`**:
      `routing decision taken` (`rule_id: R-BLOCK-90`, `disposition: reject`) and
      `call rejected by routing policy` (`method: 603`, `error_code: AS-ROUTE-002`,
      `error_detail: premium rate numbers are blocked by office policy`). The mock saw
      `SIP/2.0 603 Decline` on the trunk.
    - Counters after all three calls:
      `{"calls_total":3,"calls_by_disposition":{"completed":1,"no_match":1,"rejected":1},
      "errors_by_code":{"AS-ROUTE-001":1,"AS-ROUTE-002":1},
      "rule_hits":{"R-MOB-CM-40":1,"R-BLOCK-90":1}}`.
  - **Teardown.** `docker compose -f deploy/docker-compose.yml down` removed all three
    containers and the `as-poc-trunk` network; no container, network or volume remained and
    host ports 5060/udp, 15060-15061/udp, 8080/tcp and 8081/tcp were released.
  - **One caveat on (b).** The `100` / `180` / `200 OK` / `BYE` relay lines are emitted at
    `DEBUG`, so the `LOG_LEVEL: INFO` the compose file ships does not print them. They were
    captured by recreating the stack with `LOG_LEVEL=DEBUG` for the `as` service
    (`printf 'services:\n  as:\n    environment:\n      LOG_LEVEL: DEBUG\n' | docker compose
    -f deploy/docker-compose.yml -f - up -d --force-recreate`); no repository file was
    changed. At `INFO` the loop is visible in the Call-ID keyed trace that the same log and
    the console read, not in the log stream.
- **P3 — CI via GitHub Actions.** Push the repository and let the committed workflow run;
  record the run link/badge as the `AGENT.md` §4.8 CI-result evidence.
  **[Optional · Status: Done]** (2026-09-17)

  **Done in this conversation (2026-09-17).** The maintainer pushed `main` and the committed
  workflow `.github/workflows/ci.yml` ran on a runner for the first time:
  run [35155542999](https://github.com/dolanshu/3rdparty_AS_POC/actions/runs/35155542999),
  reported **green** — all five layers (`lint` and `type-check` in parallel, then `unit` →
  `integration` → `e2e`), every job running `uv sync --frozen`. The run link is now the
  `AGENT.md` §4.8 kind-3 CI-result evidence, recorded in the
  "Post-M4 — P3 CI via GitHub Actions" section of `docs/acceptance/report.md`; the M0–M4 and
  P1/P2 CI rows of that report now point at the same run, each stating that it is the run of
  the current `main` rather than of that milestone's code. The `README.md` header badge
  (`.../actions/workflows/ci.yml/badge.svg`) is the same result in badge form and needed no
  change. **Caveat:** no agent re-fetched the run — `gh` is not installed here and
  `web_fetch` of the run URL and the badge both timed out — so no job durations or commit
  SHA are recorded and "green" is the maintainer's statement.

  **Open:** CI does not build the images — the `docker` job in `.github/workflows/ci.yml` is
  still the commented-out TODO, so the P1/P2 compose stack has only ever been built locally.
  The run also remains independently unverified from this environment; a reviewer should open
  the link above.
- **P4 — Console browser verification.** Drive the console UI in a real browser against a live
  call (e.g. Playwright) to confirm real-time rendering and the WebSocket feed (registered
  gap, carried from M3). **[Optional · Status: Pending]** Parked by the maintainer on
  2026-09-17: it needs the Playwright browser toolchain (a browser download) and is not
  required for the POC.
- **P5 — Wheel version discovery.** Derive `as_app.__version__` from installed package metadata so
  an installed wheel is not `0.0.0+unknown` (registered gap, follow-up). **[Optional · Status:
  Done]** `src/as_app/__init__.py` now resolves `__version__` in three steps —
  `importlib.metadata.version("third-party-as-poc")` first, then the repository `VERSION` file,
  then `0.0.0+unknown` — so an installed wheel, an editable install and a bare source checkout all
  report the real version. Three unit tests cover the resolved value, the `VERSION` fallback when
  the metadata lookup fails and the last-resort placeholder; the existing
  `test_runtime_version_matches_the_version_file` still passes because `VERSION`, `pyproject.toml`
  and the installed metadata carry the same version. `docs/production-gaps.md` marks the row
  resolved and records the one remaining caveat (a wheel installed without its metadata).
- **P6 — sippy retransmission-timer shutdown fix.** Cancel per-transaction timers on
  `SipTransactionManager.shutdown()` to remove the rare failover test flake (registered gap,
  deferred). **[Optional · Status: Done]** (2026-09-18, executed as **P8a** — §3 of
  `docs/phase2-plan.md`, on the `phase2` branch; fixed on `fix/sippy-retransmission-timer`,
  merged into `main` as `d0d0501` and released as `v0.5.1`)

  **Done in this conversation (2026-09-18).** `AsStack.stop()` now cancels everything the
  stack armed before sippy's own `shutdown()` runs:
  `as_app.sip_adapter.cancel_transaction_timers()` walks both transaction tables
  (`tclient`, `tserver`) of the manager and cancels each `teA`…`teG` timer still scheduled,
  and `TrunkCallMap.dispose()` cancels the per-call no-answer timers of the calls that are
  still waiting for a next hop. sippy itself is untouched — it is an installed dependency.

  **Evidence (real commands, real output; details in the P8a section of
  `docs/acceptance/report.md`).** Two measurements, kept apart because they say different
  things. *The defect was deterministic*: every `pytest tests/integration -q -s` run printed
  at least one `TypeError: 'NoneType' object is not subscriptable` from
  `SipTransactionManager.transmitData` (5/5 sampled runs, 1–2 occurrences each). *The flake
  did not recur*: 64 consecutive `pytest tests/integration -q` runs were 64 green, 0 failures,
  so this collection never saw the 1-in-6 failure, only its cause. After the fix, same
  commands: **0 `TypeError` tracebacks in 42 `-q -s` runs** (41 green — the single failure is
  an unrelated health-endpoint test, see the report), **30/30 `-q` runs green**, **30/30**
  runs of the failover test green, `pytest tests -q` → 128 passed, all four gates green. The
  primary guard is the **deterministic** regression test (it fails on every run when the
  cancellation is removed), not the repeat loop. The gap row "Closing a transaction manager
  mid-retransmission" in `docs/production-gaps.md` is resolved, with one caveat recorded
  (in-flight transactions are cancelled, not drained: no final response reaches the peer).
- **P7 — Capture clears stale samples before writing.** `tools/capture_call.py` deleted only
  `NN-*.txt` before writing a new capture, so a run that produced fewer messages than the
  previous one could leave orphaned sample files that no longer belong to the captured call.
  It now removes every file in `docs/specs/message-samples/` except `README.md` first, so the
  directory always holds exactly the messages of the most recent capture (found during the
  post-M4 demo-steps review). **[Required · Status: Done]**

## Phase 2 — P8a … P11 (status pointers only)

**The detailed plan lives in `docs/phase2-plan.md` on the `phase2` branch.** That document is
the single detailed source for Phase 2: the strategic decisions and their rationale, the work
sequence with each item's prerequisites and known collisions, the repository and branch
strategy, and the handover protocol. `phase2` is the long-lived Phase 2 integration branch —
the copy of `docs/phase2-plan.md` on `main` is a stub pointing at it, and Phase 2 status and
plan are read and edited on `phase2`, never here.

**This section is a pointer only and must not duplicate that content.** Two copies of a plan
drift exactly the way `config/routing_rules.yaml` and `config/routing_rules.compose.yaml`
do, and that drift is already a registered production gap.

Phase 2 item status, entry states and handover notes live in `docs/phase2-plan.md` §3 **on
the `phase2` branch**. This board deliberately does not duplicate them — the reason is the
paragraph above, and the table that used to sit here had already drifted twice (it showed P8a
as "not started" after the plan recorded it done, and its P8a row named
`fix/sippy-retransmission-timer`, a branch deleted once its work had been merged into `main`).

Per-item status and handover notes are kept in `docs/phase2-plan.md` **on `phase2`**, which
every Phase 2 conversation reads on entry and updates on exit (`AGENT.md` §15).

- **P8 — anti-fraud AS. [Status: Done]** (2026-09-19, on `phase2`). A pointer only: the plan,
  status, review-gate findings and the P9 entry state live in `docs/phase2-plan.md` §3 on
  `phase2`; the acceptance evidence is in `docs/acceptance/report.md`.

- **P9 — chained demo. [Status: In progress]** (2026-09-19, on `phase2`). A pointer only: the
  plan, the Phase 1 `Call-ID` defect that paused it, the fix that lifted the pause and the
  findings the fix left behind live in `docs/phase2-plan.md` §3 on `phase2`. The defect was
  fixed as a separate item on `main` and merged back into `phase2`; stage 2 is redone on the
  fixed behaviour. It is **not** recorded here.

## Conventions

- **Single source of truth:** rules live in `AGENT.md`; live status lives here; evidence
  lives in `docs/acceptance/report.md`
- **`docs/3rdPartyAS_Poc_Introduction.pptx` is an intentional, maintained exception
  (maintainer, 2026-09-16).** It is a demo slide deck deliberately committed for reviewer
  demos and is **exempt from `AGENT.md` §4.2 "no binary diagrams"** guidance. It is not part
  of the required documentation set and is intentionally absent from the README index.
- **Commit scope:** `feat(m2): ...`, `fix(m1): ...`, `feat(m3): ...`
- **Version and tag:** one version node per milestone, tag `v<version>-m<n>`
- **Decisions:** recorded as ADRs in `docs/architecture/adr/`, referenced from code