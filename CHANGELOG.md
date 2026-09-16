# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). One
version node per milestone; the milestone tag is `v<version>-m<n>`.

## [Unreleased]

### Added

- The `docker compose` stack now completes a real call end to end (P1,
  `docs/roadmap.md`). The three images were built and run for the first time: the stack comes
  up, the mock's default `office-to-mobile` call
  (`+86216180001` → `+8613800138000`) is translated to `013800138000` by rule `R-MOB-CM-40`
  and finishes with disposition `completed`, and the console (`:8081`) and the AS internal API
  (`:8080`) answer health, metrics and the Call-ID keyed trace.
- `config/routing_rules.compose.yaml` — the deployment variant of the sample rule set: the
  same 17 rules with the `next_hops` catalogue pointed at the mock's fixed compose address
  (`172.28.0.3`). The AS originates the second leg to the hop the *rule set* selects, so the
  trunk address has to live in the rules data; `deploy/docker-compose.yml` sets
  `RULES_FILE` to this file.
- Build arguments for the package index in all three Dockerfiles (`PIP_INDEX_URL`, which pip
  reads, and `UV_DEFAULT_INDEX`, which uv reads) plus the matching `build.args` in the compose
  file. Both **default to public PyPI**, so CI and a normal checkout build exactly as before;
  a network that cannot reach PyPI overrides them for its own build, e.g.
  `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple docker compose ... build`. The
  rationale and the verified uv behaviour are in `docs/operations/deployment.md` section 4.2.

### Fixed

- The compose services could not import their own dependencies: `uv sync` installs into the
  project environment `/app/.venv`, but `CMD ["python", ...]` resolved to the **system**
  interpreter, so `as`, `s-sbc-mock` and `console` all exited immediately with
  `ModuleNotFoundError: No module named 'sippy'` (and `... 'fastapi'`). `/app/.venv/bin` is now
  first on `PATH` in each Dockerfile. Found by running the stack for the first time — no
  `docker compose config` check could have caught it.
- The AS could not reach the mock in the compose network: the canonical rule set points every
  next hop at `127.0.0.1`, and each container has its own loopback, so the AS originated the
  second leg to `127.0.0.1:15061` inside its own container, timed out
  (`AS-PEER-002`), failed over to `127.0.0.1:15062` and never reached the mock. The compose
  stack now uses `config/routing_rules.compose.yaml` (see Added).
- The image build could not finish against public PyPI on this machine. `uv sync --frozen`
  downloads the wheel URLs recorded in `uv.lock` (`files.pythonhosted.org`, measured here at
  ≈15 kB/s — a 10 MB wheel exceeds uv's 30 s HTTP timeout) and does **not** substitute the
  configured index for them, so the index build argument alone did not help. When
  `PIP_INDEX_URL` is not the public default the Dockerfiles now let uv re-resolve against that
  index; the re-resolution keeps every pinned version (same 50 packages) and writes the
  rewritten lock **inside the image only** — the committed `uv.lock` still references public
  PyPI. With the public default the build still runs `uv sync --frozen`, so a stale lock fails
  the build as before. `UV_HTTP_TIMEOUT` is raised to 180 s and the uv download cache is a
  BuildKit cache mount, so a slow link no longer fails the build outright.
- `tools/capture_call.py` now clears every previously generated sample in
  `docs/specs/message-samples/` (everything except that folder's `README.md`) before writing
  a new capture. It previously removed only `NN-*.txt`, so a capture that produced fewer
  messages than the previous run could leave orphaned sample files behind. The directory now
  always holds exactly the messages of the most recent capture (P7, `docs/roadmap.md`).

### Verified

- Compose demo run (2026-09-16, real output): `docker compose -f deploy/docker-compose.yml
  up -d` brought all three services `Up`; the mock's default call completed with Call-ID
  `e48cb46795675ab0f76f5578cf5b4449`, the AS log showing `invite received on the trunk` →
  `routing decision taken` (`R-MOB-CM-40`) → `call translated` (`+8613800138000` →
  `013800138000`, `national`) → `invite originated towards the next hop` (`s-sbc-primary`) →
  `call finished` (`disposition: completed`). The core leg carried
  `INVITE sip:013800138000@172.28.0.3:15061` with `Via: SIP/2.0/UDP 172.28.0.2:5060;rport`
  (no `0.0.0.0`), and the mock log shows
  `INVITE → 100 Trying → 180 Ringing → 200 OK → ACK → BYE → 200 OK` on both legs with the same
  Call-ID. Console: `GET :8081/healthz` → `{"status":"ok","component":"console"}`, page HTTP
  200. AS internal API: `GET :8080/healthz` →
  `{"status":"ok","version":"0.5.0","uptime_seconds":...,"rule_set_loaded":true}`,
  `GET :8080/api/v1/metrics` → `{"calls_total":1,"calls_by_disposition":{"completed":1},
  "errors_by_code":{},"rule_hits":{"R-MOB-CM-40":1},"peer_status":{...:"reachable"}}`.
  `docker compose down` left no stray container, network or volume, and the host ports were
  released.
- The full gate chain stayed green after the change: `ruff format --check .`, `ruff check .`,
  `mypy` and `pytest tests -q`.
- `uv.lock` is unchanged by a mirror build: its md5 is identical before and after a build with
  `PIP_INDEX_URL` set to a mirror, and `git status` on it stays clean.

### Changed

- The generated message samples (`docs/specs/message-samples/*.txt`) are no longer tracked:
  they are removed from the index (`git rm --cached`) and matched by a new `.gitignore`
  rule, so a `make capture` run can never dirty the working tree. The folder's `README.md`
  stays tracked as the record of the capture convention and the scenario. Documentation that
  cited the samples as committed evidence now describes them as generated and reproduced
  with `make capture`.

## [0.5.0] - 2026-09-16 — M4 Acceptance and polish (final release)

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

### Fixed

- `make demo` crashed before printing its narration when `--rules-file` was a relative path
  (which `Makefile:58` passes): `tools/demo_call.py` called `.relative_to(REPO_ROOT)` on the
  relative path against the absolute repository root, raising `ValueError`. The defect came
  from the post-M2 audit's demo upgrade (`3c322cc`) and blocked the M3 "make demo passes" DoD;
  the path is now resolved first, with a fallback for paths outside the repository.
- `docs/demo-script.md` used `--called +8613900000000` as the no-match `404` example. That
  number is covered by rule `R-MOB-CM-40` (`+86139` is a China Mobile prefix), so the call
  was in fact translated and answered `200 OK`. The example is now `+9991234567`, which
  really yields `404` / `AS-ROUTE-001` / `no_match` (found during the M4 rehearsal).
- Documented `SBC_PEER_PORT` default corrected from `15061` to the real code default `5061`
  in `README.md` and `docs/architecture/lld.md`; `15061` is the `.env.example`/mock value.
- The AS runtime version was hardcoded in `src/as_app/__init__.py` as `0.1.0`, so the
  `/healthz` payload and the `application server starting` log line served a stale version
  while `VERSION` advanced. `as_app.__version__` is now derived from the `VERSION` file, and
  `tests/unit/test_repository_baseline.py::test_runtime_version_matches_the_version_file`
  asserts the two agree so the runtime version cannot drift again.

### Documentation

- Corrected stale milestone status across the documentation set during the M4 review:
  `docs/demo-script.md` (the console section is now live, with `make dev` + `make mock` +
  `make console`), `AGENT.md` §15 (dropped the stale "current phase: M0" line),
  `docs/requirements/functional-and-nonfunctional.md` (status column `planned`/`partial` →
  `done`), `docs/README.md`, `docs/architecture/hld.md`, `docs/architecture/lld.md`,
  ADR-0002, `docs/operations/deployment.md`, `docs/operations/runbook.md` and
  `docs/specs/message-samples/README.md`.
- Corrected the M3 `/healthz` evidence in `docs/acceptance/report.md` to the value the code
  actually produces (`0.1.0`; see Known issues).

### Verified

- Full M4 acceptance run: `ruff format --check .` (66 files), `ruff check .`, `mypy`
  (20 source files) and `pytest tests -q` (119 passed after the version fix:
  98 unit + 16 integration + 5 e2e).
- Clean-checkout rehearsal from a fresh clone of the version-fix commit: `uv sync --frozen`,
  `uv lock --check` and `make demo` (exit 0) pass, and `as_app.__version__` reports `0.5.0`.
- `docs/demo-script.md` rehearsed end to end: `make demo` (exit 0), `make probe` (exit 0),
  `make rules` (exit 0), `make capture` (14 samples), the three failure branches and the
  console with a live call. Evidence is in `docs/acceptance/report.md`.
- `docker compose -f deploy/docker-compose.yml config` still validates; message samples in
  `docs/specs/message-samples/` are unchanged.

### Known issues

- `tests/integration/test_translation.py::test_next_hop_failover_uses_the_second_hop` is a
  rare (~1 in 6 runs) non-deterministic failure: `SipTransactionManager.shutdown()` cancels
  `cp_timer` but not the per-transaction retransmission timers (`t.teA`), so a pending
  `timerA` can dereference the now-`None` `global_config`, and the in-process tests share one
  `ED2` loop. Registered in `docs/production-gaps.md`; the fix is **deferred** to a separate
  conversation after M4. The suite reproduces at 119 passed.
- The AS runtime version is read from `VERSION` through a repository-relative path, so an
  installed wheel (which does not ship `VERSION`) reports `0.0.0+unknown`; registered in
  `docs/production-gaps.md` as a follow-up.

### Notes

- Version node: `0.5.0`. One version node per milestone; M4 is the final
  acceptance-and-release milestone, so the version chain is `0.1.0` (M0), `0.2.0` (M1),
  `0.3.0` (M2), `0.4.0` (M3), `0.5.0` (M4). M4 adds no user-visible capability of its own —
  it is the release that carries the acceptance run, the demo rehearsal, the documentation
  corrections and the release preparation.
- The tag `v0.5.0-m4` is created by the maintainer (agents do not tag), as for M0–M3.

## [0.4.0] - 2026-09-16 — M3 Console

### Added

- Internal API rewritten from `http.server` scaffolding to a FastAPI application served by
  uvicorn on a daemon thread (ADR-0002, `AGENT.md` §6). The app factory
  (`create_internal_api_app`) closes over the existing registries so every route handler is
  a thin read of a lock-guarded snapshot. New endpoints: `GET /api/v1/rules` (read-only
  active rule set), `GET /api/v1/traces/{call_id}` (one call), `WS /ws/events` (live event
  feed that polls the `TraceRecorder` and pushes new call traces as JSON batches).
- Console process (`src/console/main.py`): full telecom-operations UI per `AGENT.md` §4.4 —
  dark theme, top status bar (peer state, version, uptime, call counters, WebSocket
  indicator), left navigation (Call Trace / Rules / Configuration / Statistics / About),
  live message flow with direction colour coding and rule-hit highlighting, Call-ID filter,
  expandable payload viewer, inline SVG topology (S-SBC <-> AS <-> Next-Hop), statistics
  dashboard with stat cards and bar charts, rules table, configuration view. All CSS and JS
  inline — no third-party front-end libraries (REQ-NF-010). The page injects the AS API URL
  at request time. Fixed a missing `if __name__ == "__main__"` guard.
- `tests/integration/test_console.py`: 5 new tests covering ACC-M3-001 (no third-party libs,
  all four §4.4 UI surfaces, AS API URL injection) and ACC-M3-002 (internal API serves
  health/metrics/rules/traces; console runs as a separate process).
- `AGENT.md` §14: added rule 9 (delegate execution to subagents) and §14.1 (how to delegate
  via team mode).
- `pyproject.toml`: `fastapi` + `uvicorn[standard]` added to the `as` optional-dependency
  group (the internal API imports them at runtime).

### Verified

- Console page served by a real process contains dark theme (`#0d1117`), status bar labels,
  five navigation items, direction colours, rule-hit highlighting, SVG topology with S-SBC
  and AS nodes, and no external `<script src>` or `<link href>` references.
- Internal API serves `GET /healthz` -> `{"status":"ok",...}`, `GET /api/v1/metrics` ->
  counters, `GET /api/v1/rules` -> active rule set, `GET /api/v1/traces` -> call list, `GET
  /api/v1/traces/{call_id}` -> single trace (empty for unknown Call-ID).
- Console runs as a separate process that reaches the AS only through the internal API
  (ADR-0002); the served page has the AS API URL injected and no external references.
- Gates: `ruff format --check .` (66 files), `ruff check .`, `mypy` (20 source files) and
  `pytest` (118 passed, 0 skipped) are green.

### Notes

- Version node: `0.4.0` because the project gained a user-visible capability — the
  operations console and the full internal API. This is a feature addition (ADR-0002 naming
  FastAPI + uvicorn; `AGENT.md` §6 pinning it).
- The M1 `InternalApiServer` was documented as "scaffolding for the FastAPI application of
  M3"; M3 replaced it, not refactored it. The payload builder functions are unchanged.

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
