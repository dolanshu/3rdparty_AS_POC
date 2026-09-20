# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). One
version node per milestone; the milestone tag is `v<version>-m<n>`.

## [Unreleased]

### Fixed

- The outbound leg now carries its own Call-ID instead of reusing the trunk one verbatim.
  `CallController.apply_call_policy` derives a fresh `SipCallId` from the inbound one with
  sippy's own suffix `-b2b_1` (the `CCB2BUA` style, `sippy/b2bua.py`), so the second leg has
  its own dialog identity as `docs/architecture/lld.md` section 2.3 already specified. sippy
  copies a non-`None` Call-ID from the `CCEventTry` instead of generating one
  (`sippy/UacStateIdle.py`), and this AS runs a bare `sippy.UA` rather than `CCB2BUA`, which
  is why nothing rewrote it before. The route number `1` is the AS's single outbound leg,
  and every failover hop reuses the same value. `CallController.call_id` stays the trunk
  Call-ID for the log/trace correlation key. The message samples and the affected acceptance
  items (ACC-M1-002 / ACC-M1-005 / ACC-M2-005) were re-tested.

## [0.8.0] - 2026-09-20 — P10 platform extraction (Phase 2)

### Added

- The **`as-platform` library**, a new repository checked out beside this one at
  `../as_platform` (ADR-0009 decision 1). It carries the skeleton both AS instances share: the
  `observability` package (structured logging, counters and the per-Call-ID trace), the
  `errors` mechanism (the memberless `ErrorCode` base, `SIP_PHRASES`, `sip_status_for`,
  `AsError` and the skeleton `AS-CFG-* / AS-PEER-* / AS-INT-*` family), the `sip_adapter`
  boundary, the `hop` value object, the `bootstrap` plumbing, the `version` chain, the
  `call_controller` shell (`BaseCallController`, `PolicyDecision`, `BaseCallMap`), the
  `internal_api` shell and the `main` process shell (`BaseAsStack`).
- The library's two **pluggable seams, one implementation each**: `Transport` / `UdpTransport`
  and `StateStore` / `InMemoryStateStore` (`REQ-NF-020`); the second implementation of each is
  P11's.
- The library's **own test suite and its own gate** (`ruff` format and lint, `mypy`, `pytest`)
  and the three **library-standard documents** — API reference, integration guide, compatibility
  matrix (`REQ-NF-019`, `REQ-NF-021`). The library is a standalone distribution and is **not** a
  uv workspace monorepo.

### Changed

- This repository becomes the library's **reference implementation**: `src/as_app/` and
  `src/anti_fraud_as/` are now **users** of `as-platform` (`REQ-F-029`), and the library imports
  neither use case — the one-way invariant `src/as_app/**` does not import `anti_fraud_as`
  survives, and the library imports neither (`REQ-F-030`).
- The library is consumed through a **`path` source** in `pyproject.toml`
  (`path = "../as_platform"`, `editable = true`, ADR-0009 decision 6), so the `AGENT.md` §10
  guarantee *"clone → `uv sync` → `make demo`"* becomes *"clone **both** repositories side by
  side"* (`REQ-F-032`) — an explicit recorded exception, not a silent weakening.
- The extraction is **staged** (`REQ-F-033`; the §14 rule 3 waiver is recorded in
  `docs/phase2-plan.md` §8 item 2): the skeleton moved in steps that each left this repository
  building, linting and passing its three layers. It is a **pure refactor** with no wire-visible
  change — the same SIP signalling, the same `AS-*` codes and the same per-instance Call-ID keyed
  trace (`REQ-F-031`).

### Fixed

- **The routing engine's `AsError` no longer escapes to a silent trunk.** The extraction dropped
  the guard that used to wrap the policy decision, so an `AsError` raised by the routing engine
  left `decide()` without a final response on two reachable paths — `AS-ROUTE-004` / `500`
  ("translation produced an empty number", reachable from a schema-valid rules file whose
  `strip_prefix` consumes the number) and `AS-ROUTE-003` / `480` (an unresolvable hop named by a
  matched rule). The number-translation `decide()` now turns the engine's raises into a reject
  `PolicyDecision` (the application owns that conversion — ADR-0009 decision 4), restoring the
  **byte-for-byte pre-P10 trunk answer**. The application fix and its regression tests are
  `b824f11` (`src/as_app/call_controller.py`, `tests/integration/test_translation.py`); the
  library's abstract `decide()` docstring states the contract truthfully in `aaa453e`
  (`src/as_platform/call_controller.py`).

### Verified

- The P10 acceptance run: **`ACC-P10-001 … ACC-P10-008` accepted** with evidence in
  `docs/acceptance/report.md`. Local gate on this tree (item close): `ruff format --check .` →
  96 files, `ruff check .` → clean, `mypy` → no issues in 29 source files, `pytest` → **210 unit
  / 36 integration / 9 e2e**; `make demo` exits `0`; `tools/path_dependency_probe.py` exits `0`
  with `cases measured : 8`, `expectations : all held`. Library repository: `make lint` → 33
  files, clean, no issues in 15 source files; `pytest` → **84 passed**.
- **No CI run exists for any P10 commit, in either repository.** Kind ③ is not producible: the
  library has **no remote and has never been pushed**, so its workflow is an unexecuted
  definition, and this repository's five CI jobs each clone `../as_platform` before
  `uv sync --frozen`, a clone that cannot succeed while the library exists only on a filesystem
  (`docs/production-gaps.md` :134 and :131). The gate above is a **local** run, not a CI result
  (`AGENT.md` §13).

### Notes

- Version node: `0.8.0` — the Phase 2 precedent is `0.6.0` for P8 and `0.7.0` for P9 (P9.5, a
  read-only probe, opened no node). P10 produces a new repository and a library two AS instances
  share, a new capability. `VERSION` / `pyproject.toml` / `uv.lock` were updated together and the
  editable install re-synced, so `as_app.__version__` reports `0.8.0`.
- Worked on `feat/platform-extraction`, merged into `phase2` as the final step of the item close
  (`docs/phase2-plan.md` §4: an item branch merges into `phase2` when the item's own definition
  of done is met). **Not merged into `main` and not tagged** (`AGENT.md` §13/§15); the library
  repository keeps its own `VERSION` at `0.1.0` with no new node.

## [0.7.0] - 2026-09-19 — P9 chained AS topology (Phase 2)

### Added

- `make demo-chained`, backed by `tools/demo_chained_call.py`: it runs **both AS instances in
  series** (`SBC -> AS-1 anti-fraud -> AS-2 number translation -> core`) on dynamically
  allocated ports and narrates what every hop saw — an allowed call through both B2BUAs, a
  `608` reject short-circuited before AS-2, the **three distinct** per-leg dialog `Call-ID`s
  and the preserved `P-Charging-Vector` ICID. It is a **guard**, not a printout: it asserts
  those properties (including the short-circuit as an absence) and exits non-zero on any
  mismatch, and it writes nothing. `AGENT.md` section 10, `README.md`, `docs/README.md` and
  `tools/README.md` carry the new command and tool (`docs/architecture/lld.md` section 10.5).

### Fixed

- The **anti-fraud AS** had its **own copy of the same defect** on its outbound leg:
  `FraudCallController._originate_allowed` built `CCEventTry(event.getData())`, keeping the
  trunk Call-ID in element `[0]`, so the inter-AS leg reused the S-CSCF's identity. It now
  derives a fresh `SipCallId` with the shared `as_app.sip_adapter.outbound_call_id()`, exactly
  as the number-translation controller does, and rebuilds the event with every other element
  (the called number included) unchanged. The file exists only on `phase2`, which is why the
  Phase 1 fix could not reach it; the fix is what turns `tools/chained_as_probe.py` green
  (`Call-ID per leg: True`, `distinct Call-IDs: 3`). `FraudCallController.call_id` stays the
  trunk Call-ID. The integration and e2e assertions that encoded the old behaviour were
  updated to assert the derived value and its difference from the trunk one.

### Verified

- The P9 acceptance run: **`ACC-P9-001 … ACC-P9-005` accepted** with evidence in
  `docs/acceptance/report.md`. Local gate: `ruff format --check .` → 91 files, `ruff check .`
  → clean, `mypy` → no issues in 28 source files, `pytest` → **203 unit / 34 integration /
  9 e2e**. `tools/chained_as_probe.py` exits `0` with `distinct Call-IDs: 3` /
  `Call-ID per leg: True` / `ICID preserved: True`, and `make demo-chained` exits `0` with its
  five `OK` verdict lines (`allowed call completed through two B2BUAs`, `608 reject
  short-circuited before AS-2`, `Call-ID regenerated on every leg`, `three distinct Call-IDs
  across the chain`, `ICID preserved across every leg`).
- **No CI run exists for these commits**: `.github/workflows/ci.yml` triggers on `push` /
  `pull_request` and both target `main`, and nothing here is pushed — the local gate is not a
  CI result (`AGENT.md` section 13).

### Notes

- Version node: `0.7.0` — a new user-visible capability (a chained topology and its
  first-class demo). The Phase 1 precedent is `0.5.0` for M4; P8a, a defect fix, stayed
  `0.5.1`. The `VERSION` / `pyproject.toml` / `uv.lock` trio was updated together and the
  editable install re-synced, so `as_app.__version__` reports `0.7.0` and the baseline tests
  hold.
- Worked on `phase2` (P9 has no branch of its own — `docs/phase2-plan.md` §4). Tagging is the
  maintainer's step; agents do not tag.

## [0.6.0] - 2026-09-19 — P8 anti-fraud AS (Phase 2)

### Added

- A **second, independently runnable AS** — the anti-fraud / unwanted-call AS
  (`python -m anti_fraud_as.main`; ADR-0007 and `docs/phase2-plan.md` §3 P8). It screens the
  **calling** party of a trunk INVITE and returns a verdict: a caller the operator's screening
  data allows is relayed as a B2BUA with the Request-URI, the SDP body and the pass-through
  header set unchanged and **no header added**; a caller on the block list is answered
  **`608 Rejected`** (RFC 8688) from the UAS side, with **no second leg**, no media and no
  `Call-Info`. It has its own SIP listen port (default `5062`), its own declarative screening
  file `config/caller_screening.yaml`, its own internal API / console feed, its own startup
  self-check and its own stop path. It reuses the use-case-agnostic modules of `as_app` by
  direct import — no framework, no registry (ADR-0007 decision 9).
- The **verdict** is a pure function (`anti_fraud_as/screening.py`): inputs are caller
  reputation (decayed over time), a per-caller call-rate window and block/allow lists; the
  signal order is allow list → block list → rate window → reputation and the deciding signal
  is named. Cross-call state lives in a **process-level, in-memory** store
  (`anti_fraud_as/caller_state.py`) with an injected clock, never in the per-call controller
  (D9). A restart loses it — a registered POC gap, closed in P11 by the pluggable state store.
- New `AS-FRAUD-001 … AS-FRAUD-006` codes in the shared error model
  (`src/as_app/errors.py`): the three rejection reasons map to `608`, the screening-data
  failures to `500`, and `SIP_PHRASES[608] = "Rejected"` is what puts the reason phrase on the
  wire (ADR-0007). The verdict, its signals/score and the matched list entry are observable
  through counters, the Call-ID keyed trace and the read-only internal-API payloads.
- The mock S-SBC's UAC declares `Feature-Caps: *;+sip.608` in its INVITE, so the
  signalling-only AS may answer `608` without owing an announcement (RFC 8688 §3.4).
- `make fraud` (run the anti-fraud AS on its own ports) and `make demo-fraud` (two calls: one
  allowed and relayed, one rejected with `608`); `make probe-608` runs the design probe.
- `tools/demo_fraud_call.py` (the narrated two-call screening demo) and
  `tools/anti_fraud_probe.py` (the design probe that verified sippy emits `608 Rejected`
  through `CCEventFail((status, phrase, None))` — a design instrument, not a test, not in CI).
- Test layers: `tests/e2e/test_fraud_call_flows.py`,
  `tests/integration/test_fraud_screening_path.py`, and the unit files
  `test_caller_state.py`, `test_screening_engine.py`, `test_screening_data.py`,
  `test_fraud_configuration.py`, `test_fraud_error_model.py`.

### Fixed

- `tools/capture_call.py` no longer fails when `--output-dir` is a **relative** path.
  `Path.relative_to` raised `ValueError` when one side was relative and the other absolute, so
  the ADR-0007 evidence command
  `uv run python tools/capture_call.py --output-dir captures/probe` wrote its 14 samples and
  then exited `1`. The printed path is now resolved first and falls back to itself outside the
  repository, so both an absolute and a relative output directory exit `0`; `make capture`
  (absolute default) is unchanged.
- `tools/demo_fraud_call.py` no longer leaks a bare `call rejected by screening` line into its
  transcript. The tool did not configure logging, so the reject path's `WARNING` record reached
  `logging.lastResort`; it now configures the root logger at `ERROR`, so routine events stay off
  the transcript while a real failure still prints.

### Verified

- The P8 acceptance run: **`ACC-P8-001 … ACC-P8-006` accepted** with evidence in
  `docs/acceptance/report.md` — the verification commands with real output, Call-ID keyed
  allow/reject log excerpts, the honest CI position, and the capture gap recorded rather than
  filled. Local gate: `ruff format --check .` → 86 files, `ruff check .` → clean, `mypy` → no
  issues in 28 source files, `pytest tests -q` → **237 passed**. `make demo` (the Phase 1 path,
  unchanged) and `make demo-fraud` both exit `0`.
- The `608` reject path over real UDP: the probe's `final status line: SIP/2.0 608 Rejected`
  and `CCEventFail 608 'Rejected' reject path: OK`, and the integration test's assertion of the
  full on-wire line `SIP/2.0 608 Rejected` with no `Call-Info` and no second-leg INVITE.
- **No CI run exists for `phase2`**: `.github/workflows/ci.yml` triggers on `main` only, so the
  run is recorded as the maintainer's required post-merge action, not as an observed result.

### Notes

- Version node: `0.6.0` — a new user-visible capability (a second AS use case). The Phase 1
  precedent is `0.5.0` for M4; P8a, a defect fix, stayed `0.5.1`. The `VERSION` /
  `pyproject.toml` / `uv.lock` trio was updated together and the editable install re-synced, so
  `as_app.__version__` reports `0.6.0` and the baseline test holds.
- Worked on `phase2` (P8 has no branch of its own — `docs/phase2-plan.md` §4). Tagging is the
  maintainer's step; agents do not tag.

## [0.5.1] - 2026-09-18

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
- The introduction deck is committed as `docs/3rdPartyAS_Poc_Introduction.pdf` (the `.pptx`
  stays tracked beside it), and IDE / agent runtime state (`.codebuddy/`) together with
  Office lock files (`~$*`) are untracked and ignored, so neither can dirty the working tree.

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
- Stopping the AS no longer leaves per-transaction retransmission timers armed (P8a,
  `docs/phase2-plan.md` §3). sippy's `SipTransactionManager.shutdown()` cancels its own
  `cp_timer` and releases the UDP sockets but **not** the timers each transaction owns, and
  it drops the tables those timers hang from — so an INVITE still awaiting an answer kept
  retransmitting into a manager whose `global_config` was already `None`, raising
  `TypeError: 'NoneType' object is not subscriptable` in `transmitData`. Because `ED2` is a
  process-wide singleton, that stale timer fired during later, unrelated tests: it printed a
  traceback in **every** integration run and was the root cause of the rare (~1 in 6) random
  failure of `test_next_hop_failover_uses_the_second_hop`, the natural trigger being the
  failover test's own unreachable first hop. `AsStack.stop()` now cancels what the process
  armed before sippy's own shutdown: every `teA`…`teG` timer still scheduled
  (`as_app.sip_adapter.cancel_transaction_timers`) and every per-call no-answer timer
  (`TrunkCallMap.dispose()` → `CallController.dispose()`), which was a second instance of
  the same bug — it survived the manager and raised the identical `TypeError` through
  `sendResponse`. sippy itself is untouched. This also closes the gap row "Closing a
  transaction manager mid-retransmission" (`docs/production-gaps.md`); the remaining caveat
  — in-flight transactions are cancelled rather than drained, so no final response reaches
  the peer — is recorded there.
- `tools/capture_call.py` now clears every previously generated sample in
  `docs/specs/message-samples/` (everything except that folder's `README.md`) before writing
  a new capture. It previously removed only `NN-*.txt`, so a capture that produced fewer
  messages than the previous run could leave orphaned sample files behind. The directory now
  always holds exactly the messages of the most recent capture (P7, `docs/roadmap.md`).
- Four documents cited an `AGENT.md` section that does not exist. They now cite the places
  that actually carry the rules they meant: `docs/roadmap.md` (the M1 open item on scope
  conflict) cites the `AGENT.md` §15 handover protocol, which is where *"a milestone
  conversation may not change scope that belongs to another milestone"* lives;
  `docs/phase2-plan.md` (the `Related:` header, the P10 constraints, and §8 item 2, whose
  heading is now *"`AGENT.md` §14 rule 3 approval (no unconfirmed refactors)"*) cites
  `AGENT.md` §14 rule 3, which already forbids deleting code, rewriting large files or
  restructuring directories without an explicit, approved plan, with the §8 lead-in
  corrected to match — only item 1 changes a rule, item 2 is an approval an existing rule
  requires; and `tools/README.md` ("Rules for new tools", §14.6) cites `AGENT.md` §14 rule 6
  (report honestly), which is the rule *"Do not claim passed tests, verified behaviour or
  working calls that were not executed"*. Documentation only; `AGENT.md` itself is
  unchanged.

### Verified

- **P8a evidence (2026-09-18, real commands; two separate measurements, not merged).**
  *The defect* is deterministic: 5/5 `pytest tests/integration -q -s` runs before the fix
  printed at least one `TypeError` traceback from `SipTransactionManager.transmitData` (four
  runs 1, one run 2). *The flake* is not: 64 consecutive `pytest tests/integration -q` runs
  before the fix were **64 green, 0 failures**, so the 1-in-6 failure did not recur and was
  never reproduced — only its cause was. After the fix, with the same commands: **0 `TypeError`
  tracebacks in 42 `-q -s` runs** (41 green; the one failure is a different, unrelated test —
  see `docs/acceptance/report.md`), **30/30 `-q` runs green** with the command identical to
  the 64 pre-fix runs, and **30/30** runs of
  `test_next_hop_failover_uses_the_second_hop` green. `pytest tests -q` → 128 passed and all
  four gates are green. **The primary guard is the deterministic regression test, not the
  repeat loop**: it fails on every run when the cancellation is removed
  (`AssertionError: 2 timer(s) still armed on a stopped transaction manager`).
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
- **P3 — CI via GitHub Actions ran green (2026-09-17, `docs/roadmap.md`).** The maintainer
  pushed `main` and the committed workflow `.github/workflows/ci.yml` ran on a runner for the
  first time: run
  [35155542999](https://github.com/dolanshu/3rdparty_AS_POC/actions/runs/35155542999),
  **green** across the five layers (`lint` and `type-check` in parallel, then `unit` →
  `integration` → `e2e`, every job running `uv sync --frozen`). The run link is now recorded
  as the `AGENT.md` §4.8 kind-3 CI-result evidence in `docs/acceptance/report.md`, replacing
  the `not executed` / `not observed` verdict the M0–M4, P1 and P2 sections had to carry —
  each of them now states that the run is of the current `main`, not of that milestone's
  code. **Caveat:** not independently re-fetched from this environment — `gh` is not
  installed and `web_fetch` of the run URL timed out, so no job durations or commit SHA are
  recorded and "green" is the maintainer's statement.
- **P2 — Manual testing gate passed (2026-09-16, `docs/roadmap.md`).** The **human sign-off
  was performed by the maintainer on 2026-09-16**; P2 is a human gate and no agent performed
  it. The machine evidence for the review was gathered from the live stack and covers all five
  items, including (e), which was still open after P1: (a) all three services `Up` in
  `docker ps`; (b)+(c) the default call, Call-ID `6d415fc865955c05162309eadd9416a5`, shows the
  full `INVITE -> 100 -> 180 -> 200 OK -> BYE` loop in the AS structured log with
  `call translated` (`rule_id: R-MOB-CM-40`, `+8613800138000` -> `013800138000`) and the
  translated Request-URI `sip:013800138000@172.28.0.3:15061` on the wire; (d) the console
  answers `GET :8081/healthz` and serves its page (HTTP 200, 16754 bytes, no external
  references) and reaches `http://as:8080/api/v1/traces`; (e) both failure branches were placed
  on the live stack — `+9991234567` -> `404` / `AS-ROUTE-001` / `no_match`
  (Call-ID `fff8f9d4d34122326a6f7ffe8f157959`) and `+861681234567` -> `603` / `AS-ROUTE-002` /
  `R-BLOCK-90` (Call-ID `cd3b2b396d1e7a29074f119ee6d1b318`). `docker compose down` left no
  container, network or volume behind. Evidence in `docs/acceptance/report.md`.

### Changed

- `as_app.__version__` is now derived from the installed package metadata before the
  repository `VERSION` file (P5, `docs/roadmap.md`): `src/as_app/__init__.py` resolves it in
  three steps — `importlib.metadata.version("third-party-as-poc")`, then `VERSION`, then
  `0.0.0+unknown`. An installed wheel no longer reports `0.0.0+unknown` on `/healthz` and in
  the `application server starting` log line, because it carries distribution metadata even
  though it ships no `VERSION` file. Three unit tests cover the resolved value, the
  `VERSION` fallback when the metadata lookup fails, and the last-resort placeholder.
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
