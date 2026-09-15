# Acceptance criteria

One row per acceptance item: criterion, verification command, expected result, related
requirement. An item is accepted only with evidence per `AGENT.md` section 4.8; the
evidence is recorded in `docs/acceptance/report.md`.

Legend: **accepted** — executed with evidence · **open** — not executed yet ·
**planned** — belongs to a later milestone.

## M0 — Foundation

| ID | Criterion | Verification command | Expected result | Requirement |
| --- | --- | --- | --- | --- |
| ACC-M0-001 | Repository skeleton and meta files exist exactly as `AGENT.md` section 5 | `uv run pytest tests/unit/test_repository_baseline.py -q` | all checks pass (directories, meta files, no forbidden module names, licence header in every source file) | REQ-NF-007 |
| ACC-M0-002 | `uv` installs the locked environment and sippy 2.4.2 runs a minimal stack on Python 3.10 | `uv sync --frozen && uv run python tools/sippy_probe.py` | `sippy : 2.4.2`, a `404` response to the probe INVITE, last line `minimal SipTransactionManager + ED2.loop() stack: OK` | REQ-NF-003, REQ-NF-008 |
| ACC-M0-003 | Documentation baseline per `AGENT.md` section 4.2 is present | `uv run pytest tests/unit/test_repository_baseline.py -q -k documentation` | all checks pass (SRS, HLD, LLD, operations, acceptance, demo script, glossary, production gaps) | REQ-NF-007 |
| ACC-M0-004 | Sample routing data meets `AGENT.md` section 4.6 | `uv run python tools/show_rules.py` | 10–20 rules with priorities, ranges across several operators plus special service numbers, at least two next hops with priority and failover, all four number formats exercised | REQ-F-003, REQ-F-004, REQ-F-005 |
| ACC-M0-005 | Configuration knobs of `AGENT.md` section 8 are declared and the startup self-check passes | `uv run python -m as_app.main --self-check-only; echo $?` | exit code `0` and a log line with `event: startup self-check passed` | REQ-F-013, REQ-F-014 |
| ACC-M0-006 | A changed rules file is picked up; an invalid one keeps the previous rule set | `uv run pytest tests/integration -q -k reloaded` | the test passes: reload activates the new file, and a broken edit leaves the previous rule set active | REQ-F-005 |
| ACC-M0-007 | Structured logging with the mandatory field set and the `AS-*` error model | `uv run pytest tests/unit/test_observability.py tests/unit/test_errors.py -q` | all tests pass; every log line carries `timestamp`, `level`, `module`, `call_id`, `direction`, `peer`, `event` | REQ-F-010, REQ-F-015, REQ-NF-005 |
| ACC-M0-008 | ADR-0001 … ADR-0006 exist with context, decision and consequences | `ls docs/architecture/adr/` | six files, `0001` … `0006` | REQ-NF-007 |
| ACC-M0-009 | Quality gates configured and green: ruff (format + lint), mypy, pytest | `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest tests -q` | each command exits `0`; pytest reports the unit, integration and e2e layers (e2e skipped until M1) | REQ-NF-004, REQ-NF-008 |
| ACC-M0-010 | No secrets, certificates, environment files or real traffic captures are committed | `git grep -nE "BEGIN (RSA|EC|DSA|OPENSSH|PRIVATE) KEY" -- . ; test ! -e .env ; git status --porcelain` | no matches, no `.env` file, no unintended files in `git status` | REQ-NF-006 |
| ACC-M0-011 | CI workflow runs the gates in layers and verifies the lock file | `uv run python -c "import yaml,pathlib;print(sorted(yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())['jobs']))"` | `['e2e', 'integration', 'lint', 'type-check', 'unit']` | REQ-NF-008 |
| ACC-M0-012 | Production gap register contains the baseline of `AGENT.md` section 3 | `grep -c '^| ' docs/production-gaps.md` | 13 or more table rows, one per baseline area (transport, authentication, topology, core network, header handling, transactions, reliability, media, charging, security, observability, configuration, capacity) | REQ-NF-007 |

## M1 — Signalling path (executed 2026-09-16)

| ID | Criterion | Verification command | Expected result | Requirement |
| --- | --- | --- | --- | --- |
| ACC-M1-001 | A complete call runs: `INVITE → 100 → 180 → 200 OK → ACK → BYE` | `uv run pytest tests/e2e -q -k complete_call` | the e2e test passes and prints a Call-ID keyed trace | REQ-F-002, REQ-F-009 |
| ACC-M1-002 | Headers and SDP pass through unmodified | `uv run pytest tests/integration -q -k pass_through` | the outbound INVITE carries the same headers and body, only the Request-URI differs | REQ-F-008 |
| ACC-M1-003 | A request from an unlisted source is rejected with `403` and `AS-PEER-001` | `uv run pytest tests/integration -q -k peer` | the test passes | REQ-F-007 |
| ACC-M1-004 | Counters, health endpoint and graceful `SIGTERM` shutdown work | `uv run pytest tests/integration -q -k lifecycle` | the test passes; `/healthz` answers `{"status":"ok",...}`, `/api/v1/metrics` serves the counters, and the log ends with `shutdown complete` and `reason: signal SIGTERM` (exit code `0`) | REQ-F-011 |
| ACC-M1-005 | Message samples are captured from a real call, never hand-written | `uv run python tools/capture_call.py` | 14 files written to `docs/specs/message-samples/` following `NN-direction-method[-qualifier].txt`, one per message of `INVITE → 100 → 180 → 200 → ACK → BYE`; headers and SDP of `01-in-invite-trunk.txt` reappear unchanged in `03-out-invite-core.txt` | REQ-NF-007 |
| ACC-M1-006 | The mock S-SBC runs as its own process and answers the AS on configurable ports | `docker compose -f deploy/docker-compose.yml config` and `uv run python -m s_sbc_mock.main --help` | the compose file validates and lists the `s-sbc-mock` service with UDP ports; the process entry point exposes `--listen-address`, `--listen-port`, `--trunk-port`, `--as-address`, `--as-port`, `--call` and `--repeat` | REQ-F-001, REQ-NF-009 |

## M2 — Number translation (executed 2026-09-16)

| ID | Criterion | Verification command | Expected result | Requirement |
| --- | --- | --- | --- | --- |
| ACC-M2-001 | The Request-URI and number format are rewritten per rules | `uv run pytest tests/e2e -q -k translation` | `+8613800138000` leaves the AS as `013800138000` (rule `R-MOB-CM-40`) | REQ-F-003 |
| ACC-M2-002 | Next hop failover is used when the first hop is unavailable | `uv run pytest tests/integration -q -k failover` | the second next hop receives the INVITE and the call completes with `200 OK` | REQ-F-004 |
| ACC-M2-003 | Error branches: `404`, `603`, `CANCEL` | `uv run pytest tests/e2e -q` | all error-branch tests pass (`404` / `AS-ROUTE-001`, `603` / `AS-ROUTE-002`, `CANCEL`); `480` / `500` covered at unit level | REQ-F-006 |
| ACC-M2-004 | YAML hot reload: a changed rules file activates at runtime; a broken one keeps the previous rule set | `uv run pytest tests/integration -q -k reload` | both reload tests pass (ADR-0004) | REQ-F-005 |
| ACC-M2-005 | Translated-call message samples captured, not hand-written | `uv run python tools/capture_call.py` | 14 files in `docs/specs/message-samples/`; `01-in-invite-trunk.txt` carries `+8613800138000`, `03-out-invite-core.txt` carries `013800138000`, same Call-ID | REQ-NF-007 |

## M3 — Console (planned)

| ID | Criterion | Verification command | Expected result | Requirement |
| --- | --- | --- | --- | --- |
| ACC-M3-001 | Console shows live flow, rule hit, statistics and topology, with no third-party front-end libraries | `uv run pytest tests/integration -q -k console` | the test passes; no external script or stylesheet reference in the page | REQ-F-012, REQ-NF-010 |
| ACC-M3-002 | Internal API serves health, metrics, rules and traces | `curl -s http://127.0.0.1:8080/healthz` | `{"status":"ok",...}` | REQ-F-011 |

## M4 — Acceptance and polish (planned)

| ID | Criterion | Verification command | Expected result | Requirement |
| --- | --- | --- | --- | --- |
| ACC-M4-001 | Every acceptance item carries the four kinds of evidence | review of `docs/acceptance/report.md` | no item without evidence | REQ-NF-007 |
| ACC-M4-002 | `docs/demo-script.md` rehearsed end to end | `make demo` | the narrated flow completes | REQ-NF-008 |
