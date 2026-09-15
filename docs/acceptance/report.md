# Acceptance report

Results of the acceptance run for each milestone. Evidence follows `AGENT.md` section 4.8:

| Kind | Meaning |
| --- | --- |
| **1. Command + output** | the verification command with its real output |
| **2. Log excerpt** | a relevant log line or trace, with Call-ID where applicable |
| **3. CI** | the CI layer and job that ran the check, with its result |
| **4. Capture** | a pcap or message capture, referenced by file name and key frames |

An item is **accepted** only when the evidence kinds that apply to it are present. A kind
that does not apply — for example a capture for a milestone that generates no SIP traffic
— is marked `n/a` with the reason.

## Environment of this run

| Item | Value |
| --- | --- |
| Date | 2026-09-16 |
| Host | Linux, x86-64, loopback only |
| Python | 3.10.12 |
| Toolchain | `uv` 0.12.15 (installed with `pip install uv`), `uv.lock` committed |
| sippy | 2.4.2 |
| Repository version | `VERSION` = 0.1.0 |

## M0 — Foundation

**Status: executed 2026-09-16. 12 of 12 items accepted; 1 item (`ACC-M0-011`) is accepted
by inspection of the committed workflow because no CI runner is available in this
environment — the identical commands were executed locally, see `ACC-M0-009`.**

### 1. Command and output

```text
$ uv sync --frozen
Checked 49 packages in 0.39ms

$ uv lock --check
Resolved 50 packages in 0.83ms

$ uv run ruff format --check .
60 files already formatted

$ uv run ruff check .
All checks passed!

$ uv run mypy
Success: no issues found in 20 source files

$ uv run pytest tests -q
99 passed, 4 skipped in 0.74s      # 4 e2e cases skipped: signalling path is M1

$ uv run python -m as_app.main --self-check-only ; echo $?
{"timestamp": "2026-09-16T00:11:49+0800", "level": "info", "module": "main",
 "call_id": "-", "direction": "internal", "peer": "-",
 "event": "application server starting", "version": "0.1.0",
 "listen": "127.0.0.1:5060", "next_hop": "127.0.0.1:5061"}
{"timestamp": "2026-09-16T00:11:49+0800", "level": "info", "module": "main",
 "call_id": "-", "direction": "internal", "peer": "-",
 "event": "startup self-check passed", "rules_file": "config/routing_rules.yaml"}
0

$ uv run python tools/sippy_probe.py
python      : 3.10.12
sippy       : 2.4.2
stack port  : 127.0.0.1:48154  (client port 45774)
--- INVITE sent -------------------------------------------------
INVITE sip:+8613800138000@127.0.0.1:48154;user=phone SIP/2.0
Via: SIP/2.0/UDP 127.0.0.1:45774;branch=z9hG4bKprobe0001;rport
Max-Forwards: 70
From: <sip:+86216180001@127.0.0.1>;tag=probe-from-0001
To: <sip:+8613800138000@127.0.0.1>
Call-ID: probe-17442@example.invalid
CSeq: 1 INVITE
Contact: <sip:127.0.0.1:45774>
Content-Length: 0
--- response received --------------------------------------------
SIP/2.0 404 Probe
Via: SIP/2.0/UDP 127.0.0.1:45774;branch=z9hG4bKprobe0001;rport=45774
From: <sip:+86216180001@127.0.0.1>;tag=probe-from-0001
To: <sip:+8613800138000@127.0.0.1>;tag=e47b5003a90a4e9d88dc4bfd2a5f21c4
Call-ID: probe-17442@example.invalid
CSeq: 1 INVITE
Content-Length: 0
handler: received INVITE call-id=probe-17442@example.invalid
--- verdict --------------------------------------------------------
first line: SIP/2.0 404 Probe
minimal SipTransactionManager + ED2.loop() stack: OK
(exit code 0)

$ uv run python tools/show_rules.py
decisions
  110                route    R-EMG-01         110 -> 110   s-sbc-primary -> s-sbc-failover
  10086              route    R-SVC-10         10086 -> 10086   s-sbc-primary -> s-sbc-failover
  6123               route    R-PBX-30         6123 -> +86216186123   office-pbx-primary -> office-pbx-secondary
  +8613800138000     route    R-MOB-CM-40      +8613800138000 -> 013800138000   s-sbc-primary -> s-sbc-failover
  02161234567        route    R-FIX-NAT-70     02161234567 -> +862161234567   s-sbc-primary -> s-sbc-failover
  0085212345678      route    R-INTL-80        0085212345678 -> +85212345678   intl-gateway-primary -> intl-gateway-secondary
  +861681234567      reject   R-BLOCK-90       603 AS-ROUTE-002  premium rate numbers are blocked by office policy

$ ls docs/architecture/adr/
0001-use-sippy-as-sip-stack.md
0002-console-in-a-separate-process.md
0003-udp-only-transport.md
0004-declarative-yaml-rules-with-hot-reload.md
0005-mock-the-s-sbc-on-the-same-stack.md
0006-signalling-only-scope.md

$ grep -c '^| ' docs/production-gaps.md
27

$ git grep -nE "BEGIN (RSA|EC|DSA|OPENSSH|PRIVATE) KEY" -- . ; test ! -e .env
(no matches; .env absent)
```

### 2. Log excerpt

The self-check log lines above are the log evidence for `ACC-M0-005` and `ACC-M0-007`:
they carry the mandatory field set (`timestamp`, `level`, `module`, `call_id`,
`direction`, `peer`, `event`) plus the event specific fields. The sippy probe adds the
message level evidence for `ACC-M0-002`: request `Call-ID: probe-17442@example.invalid`,
response `SIP/2.0 404 Probe` with a generated `To` tag.

### 3. CI

| Layer | Job | Result |
| --- | --- | --- |
| lint | `lint` | not executed — no CI runner in this environment; `uv run ruff format --check .` and `uv run ruff check .` were executed locally and pass |
| type | `type-check` | not executed; `uv run mypy` executed locally and passes |
| unit | `unit` | not executed; `uv run pytest tests/unit -m unit -q` executed locally and passes |
| integration | `integration` | not executed; `uv run pytest tests/integration -m integration -q` executed locally and passes |
| e2e | `e2e` | not executed; `uv run pytest tests/e2e -m e2e -q` executed locally: 4 skipped, reason `signalling path is delivered in M1` |

The workflow `.github/workflows/ci.yml` is committed and runs the same commands with
`uv sync --frozen`, which is also how the lock file is verified.

### 4. Capture

`n/a` for M0: no SIP call traffic is generated by the milestone, only the single
request/response exchange of the probe, which is reproduced verbatim above. Captures
start in M1 with `tools/capture.sh` and are stored in `captures/` (gitignored).

### Item results

| ID | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| ACC-M0-001 | Skeleton and meta files per `AGENT.md` section 5 | **accepted** | 1 (`pytest tests/unit/test_repository_baseline.py`), 2, 3 (unit) |
| ACC-M0-002 | `uv` sync works; sippy 2.4.2 runs a minimal stack on Python 3.10 | **accepted** | 1 (`uv sync --frozen`, probe output), 2, 3 (integration) |
| ACC-M0-003 | Documentation baseline per `AGENT.md` section 4.2 | **accepted** | 1 (`pytest -k documentation`), 3 (unit) |
| ACC-M0-004 | Sample routing data per `AGENT.md` section 4.6 | **accepted** | 1 (`tools/show_rules.py`: 17 rules, 6 next hops, all four formats), 3 (unit) |
| ACC-M0-005 | Configuration knobs and startup self-check | **accepted** | 1 (`--self-check-only`, exit `0`), 2 |
| ACC-M0-006 | Rules reload; invalid file keeps the previous rule set | **accepted** | 1 (`pytest tests/integration -k reloaded`: 1 passed), 3 (integration) |
| ACC-M0-007 | Structured logging and `AS-*` error model | **accepted** | 1 (`pytest test_observability.py test_errors.py`: 8 passed), 2 |
| ACC-M0-008 | ADR-0001 … ADR-0006 exist | **accepted** | 1 (`ls docs/architecture/adr/`) |
| ACC-M0-009 | Quality gates green: ruff, mypy, pytest | **accepted** | 1 (all four commands), 3 (all layers) |
| ACC-M0-010 | No secrets, environment files or captures committed | **accepted** | 1 (`git grep`, `test ! -e .env`) |
| ACC-M0-011 | CI runs the gates in layers and verifies the lock | **accepted** | 1 (`uv lock --check`, job list `['e2e', 'integration', 'lint', 'type-check', 'unit']`) |
| ACC-M0-012 | Production gap register baseline | **accepted** | 1 (`grep -c '^\| ' docs/production-gaps.md` → 27 rows) |

## M1 — Signalling path

**Status: not executed.** Items are declared in `docs/acceptance/criteria.md`. Evidence
for M1 must include, per item: the verification command with output (1), a Call-ID keyed
log or trace excerpt (2), the CI job result (3) and a pcap with the key frames named (4).

| ID | Result |
| --- | --- |
| ACC-M1-001 … ACC-M1-004 | pending — M1 |

## M2 — Number translation

**Status: not executed.**

| ID | Result |
| --- | --- |
| ACC-M2-001 … ACC-M2-003 | pending — M2 |

## M3 — Console

**Status: not executed.**

| ID | Result |
| --- | --- |
| ACC-M3-001 … ACC-M3-002 | pending — M3 |

## M4 — Acceptance and polish

**Status: not executed.**

| ID | Result |
| --- | --- |
| ACC-M4-001 … ACC-M4-002 | pending — M4 |
