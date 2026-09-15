# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). One
version node per milestone; the milestone tag is `v<version>-m<n>`.

## [Unreleased]

### Changed

- `make demo` now places a real trunk call and narrates it (`tools/demo_call.py`): the
  routing decision, the Request-URI before and after number translation, every message on
  the wire and the outcome. It writes nothing to the repository, so the demo is repeatable
  and read-only. The previous rule-table view moved to `make rules`.
- Capture determinism: `tools/capture_call.py` keeps the event loop alive for a settle
  window (0.3 s) after the call is released, so the final `200 OK` answering the relayed
  `BYE` is always recorded. Three consecutive captures now produce the same 14 samples; a
  run could previously stop at 13, leaving the `14-in-200-trunk.txt` that the acceptance
  report and the sample README reference missing.
- Documentation aligned with M2: milestone status, M2 evidence figures, sample references,
  demo script and readiness notes no longer describe the call demo as unavailable.

## [0.3.0] - 2026-09-16 — M2 Number translation

### Added

- Number translation seam: `CallController.apply_call_policy` is the single place that
  rewrites the called number before the outbound INVITE. It calls
  `as_app.routing.engine.decide`, rebuilds the `CCEventTry` with the translated called
  number, and attaches pass-through headers. SDP still passes through verbatim (M1 rule,
  unchanged). `+8613800138000` (E.164) leaves the AS as `013800138000` (national) per
  rule `R-MOB-CM-40`.
- Error branches wired to the error code system (`src/as_app/errors.py`): no matching
  rule -> `404` / `AS-ROUTE-001`; policy rejection -> `603` / `AS-ROUTE-002`; no next
  hop -> `480` / `AS-ROUTE-003`; translation yields empty -> `500` / `AS-ROUTE-004`;
  caller abandons -> `CANCEL` handled cleanly.
- Next-hop failover: the `CallController` owns a controller-managed no-answer timer
  (`_DEFAULT_NEXT_HOP_EXPIRE = 3.0` s) that tears the serving hop down when it does not
  answer; `_relay_from_next_hop` tries the next hop from the decision's ordered list and
  records which hop served the call.
- YAML hot reload: `AsStack.run` starts a loop-owned timer
  (`RULE_RELOAD_POLL_SECONDS = 1.0`) that calls `RuleSetStore.maybe_reload()`; a changed
  rules file activates a new rule set with a `rule set reloaded` log line naming the new
  rule set, and a broken edit keeps the previous rule set (ADR-0004 fail-safe reload).
- `tests/integration/test_translation.py`: next-hop failover, hot reload (success and
  fail-safe), `480` / `AS-ROUTE-003`, `500` / `AS-ROUTE-004` coverage.
- `tests/e2e/test_call_flows.py`: the two M1-skipped cases (`404`, `603`) are
  un-skipped and pass; a translation assertion case is added.
- `tools/capture_call.py` rewrites next-hop ports to the mock core port so the captured
  call reaches the mock; `docs/specs/message-samples/` regenerated with the translated
  Request-URI.

### Verified

- `+8613800138000` leaves the AS as `013800138000` (rule `R-MOB-CM-40`, Call-ID
  `07c49b41b5aaa5724a015ffffa67839c` in the captured samples).
- `404` / `AS-ROUTE-001` for `+9991234567`; `603` / `AS-ROUTE-002` for `+861681234567`
  (rule `R-BLOCK-90`); `CANCEL` for caller abandonment — all e2e.
- Next-hop failover: a call completes via the second hop when the first is unreachable
  (integration test).
- Hot reload: a changed rules file activates at runtime; a broken edit keeps the previous
  rule set (integration tests).
- Gates: `ruff format --check .` (64 files), `ruff check .`, `mypy` (20 source files) and
  `pytest` (113 passed, 0 skipped) are green; `docker compose -f
  deploy/docker-compose.yml config` validates.

### Notes

- Version node: the maintainer tagged this milestone `0.3.0`, because the AS gained a
  user-visible capability — it now translates numbers and handles error branches — which
  reads as a feature addition. M1 was retroactively assigned `0.2.0` so the version chain
  is continuous (`0.1.0` M0, `0.2.0` M1, `0.3.0` M2).

## [0.2.0] - 2026-09-16 — M1 Signalling path

### Added

- B2BUA call control: `CallController` in `src/as_app/call_controller.py` terminates the
  trunk INVITE on `uaA`, originates the second leg on `uaO` towards the configured next
  hop and relays sippy call control events between the two legs.
- `TrunkCallMap`, the process-wide trunk entry point: rejects a request whose source is
  not in `ALLOWED_PEERS` with `403 Forbidden` and `AS-PEER-001` before any call state is
  created, answers `481` for an unknown in-dialog request and `501` for anything but
  `INVITE`.
- Header and SDP pass-through: the headers of `PASSTHROUGH_HEADERS`
  (`src/as_app/sip_adapter.py`) and the message body are copied unchanged onto the
  outbound INVITE. Number translation is a documented seam
  (`CallController.apply_call_policy`) that M1 leaves as a verbatim relay.
- `AsStack` in `src/as_app/main.py`: `SipConf` + `SipTransactionManager` + `ED2.loop()`,
  with a loop-owned timer that stops the loop once a signal handler has requested
  shutdown.
- `InternalApiServer` in `src/as_app/internal_api.py`: health (`/healthz`), counters
  (`/api/v1/metrics`) and traces (`/api/v1/traces`) on their own thread, from the payload
  builders M0 defined. Scaffolding for the FastAPI application of M3.
- `SipMessageRecorder` in `src/as_app/observability/tracing.py`, which records the verbatim
  SIP messages sippy writes.
- Mock S-SBC implemented: `src/s_sbc_mock/uac.py` places the triggered INVITE with an
  ISC-flavoured header set and an SDP offer, `src/s_sbc_mock/uas.py` answers `180 Ringing`
  and `200 OK` and releases with `BYE`, and `src/s_sbc_mock/main.py` runs both sides as
  one process on configurable ports (`--listen-port`, `--trunk-port`, `--as-port`,
  `--call`, `--repeat`).
- `tools/capture_call.py`: runs a real call over loopback UDP and writes every message to
  `docs/specs/message-samples/` using the naming convention of that folder.
- `tests/e2e/test_call_flows.py` (replaces `test_call_flows_pending.py`) and
  `tests/integration/test_signalling_path.py`; `tests/conftest.py` gained a `TrunkPair`
  fixture that binds AS and mock on ephemeral ports and drives the shared sippy loop.

### Verified

- `INVITE → 100 → 180 → 200 OK → ACK → BYE` completes over real UDP, both as two processes
  (AS `127.0.0.1:45573`, mock core `127.0.0.1:47333`, mock trunk `127.0.0.1:46826`, both
  exiting `0` on `SIGTERM`) and in the e2e suite (Call-ID
  `4dad63799c88fe9482e804a862613323`).
- Headers and SDP arrive unchanged on the far side; the captured samples
  `01-in-invite-trunk.txt` and `03-out-invite-core.txt` show it for Call-ID
  `66214a32501ea3d6a9aaf48db78f1a6c`.
- An INVITE from `127.0.0.2` is answered `SIP/2.0 403 Forbidden` and logged with
  `AS-PEER-001` (Call-ID `peer-demo-4711@example.invalid`).
- Gates: `ruff format --check .` (63 files), `ruff check .`, `mypy` (20 source files) and
  `pytest` (105 passed, 2 skipped for M2) are green; `docker compose -f
  deploy/docker-compose.yml config` validates.

### Notes

- Version node: the maintainer assigned `0.2.0` (retroactively, at the post-M2 audit) so
  the version chain matches the one-version-node-per-milestone rule, because the AS gained
  a user-visible capability — it now completes calls — which reads as a feature addition
  rather than as a fix.
- Two e2e cases were declared and skipped in M1 (`404` and `603`); M2 — Number translation
  un-skipped and passed them.

## [0.1.0] - 2026-09-15 — M0 Foundation

### Added

- Repository skeleton per `AGENT.md` section 5: `config/` `deploy/` `docs/` `src/`
  `tests/` `tools/` and the meta files (`VERSION`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `NOTICE`, `LICENSE`, `Makefile`, `.env.example`,
  `.gitignore`).
- Toolchain: `pyproject.toml` (Python 3.10, sippy 2.4.2) with a committed `uv.lock`;
  `ruff` (format + lint), `mypy` and `pytest` configured in `pyproject.toml`. The three
  packages under `src/` are installed editable, so `uv sync` alone is enough to run
  `python -m as_app.main`.
- CI workflow `.github/workflows/ci.yml` running the gates in layers: lint, type check,
  unit, integration, e2e; the lock file is verified with `uv sync --frozen`.
- Documentation baseline per `AGENT.md` section 4.2: documentation map, SRS
  (`REQ-F-*`, `REQ-NF-*`), HLD, LLD, ADR-0001 … ADR-0006, operations guides
  (deployment, runbook, troubleshooting), acceptance criteria and report template,
  demo script, glossary and the production gap register.
- Sample office routing data (17 rules, 6 next hops) in `config/routing_rules.yaml` with
  the Pydantic model, loader and reload detection in `src/as_app/routing/`.
- `src/as_app/` skeleton: settings and startup self-check, error model, sippy adapter
  boundary, call controller hook, routing engine, structured logging, counters, per
  Call-ID tracing and the internal API payloads used by the console.
- `src/console/` and `src/s_sbc_mock/` process skeletons, `deploy/docker-compose.yml`
  with the three services and UDP ports, and `tools/` with the sippy probe, the rule
  viewer and the capture helper.
- `README.md` with positioning, architecture, quickstart, repository tour, non-goals and
  the documentation index.

### Verified

- sippy 2.4.2 installs and runs a minimal `SipTransactionManager` + `ED2.loop()` stack on
  Python 3.10.12: one INVITE in, `SIP/2.0 404 Probe` out, verdict line
  `minimal SipTransactionManager + ED2.loop() stack: OK`. The full probe output is
  recorded in `docs/acceptance/report.md`.
- All 12 M0 acceptance items executed; `uv sync --frozen`, `uv lock --check`,
  `ruff format --check`, `ruff check`, `mypy` and the three pytest layers are green
  (100 passed, 4 e2e cases skipped until M1).
- `make demo`, `make probe`, `make lint`, `make test` verified; graceful shutdown on
  `SIGTERM` logs `shutdown complete`; the console process answers `GET /healthz`;
  `docker compose -f deploy/docker-compose.yml config` validates (images not built).

### Notes

- `make demo` is still a stub: it shows the active rule set and states that the call demo
  lands in M1. The e2e cases are declared and skipped for the same reason.
