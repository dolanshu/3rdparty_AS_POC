# Runbook

Routine operations for the POC. Every command is run from the repository root unless
stated otherwise.

## 1. Start and stop

| Action | Command |
| --- | --- |
| Sync the environment | `uv sync` |
| Start the AS | `make dev` (or `uv run python -m as_app.main`) |
| Start the anti-fraud AS | `make fraud` (or `uv run python -m anti_fraud_as.main`, trunk on 5062) |
| Start the mock | `make mock` (places the default call on startup) |
| Start the console | `make console` (console UI on 127.0.0.1:8081) |
| Start everything with compose | `make docker-up` |
| Stop everything | `make docker-down` |
| Stop a foreground process | `Ctrl-C` — expect the `shutdown complete` log line |

Both AS processes are independent: `make dev` and `make fraud` can run side by side because
the anti-fraud AS listens on `5062`, not `5060`.

## 2. Reload the routing rules

Rules are data (`ADR-0004`). Edit `config/routing_rules.yaml` and let the store pick the
change up:

```bash
# 1. edit the file
$EDITOR config/routing_rules.yaml

# 2. validate it the way the AS does
uv run python -m as_app.main --self-check-only

# 3. see what it decides
uv run python tools/show_rules.py --evaluate +8613800138000
```

`RuleSetStore.maybe_reload()` compares size and modification time. If the new file is
invalid, the **previous rule set stays active** and the error is logged with `AS-RULE-00x`.

### Screening data (anti-fraud AS)

The anti-fraud AS reloads `config/caller_screening.yaml` the same way, from a loop-owned
timer:

```bash
# 1. edit the block/allow lists or the window/reputation parameters
$EDITOR config/caller_screening.yaml

# 2. validate it the way the AS does
uv run python -m anti_fraud_as.main --self-check-only

# 3. inspect the active data (needs a running anti-fraud AS on 8082)
curl -s http://127.0.0.1:8082/api/v1/screening
```

`ScreeningDataStore.maybe_reload()` also compares size and modification time. A successful
reload re-applies the window and reputation parameters to the process-level state, so an
operator change takes effect without a restart; an invalid edit logs `AS-FRAUD-005` and the
**previous data stays active**. Note that the call-rate window and the reputation history are
kept across the reload — the data describes the thresholds, the callers keep their history.

## 3. Inspect state

| What | How |
| --- | --- |
| Active rule set | `uv run python tools/show_rules.py` |
| Decision for one number | `uv run python tools/show_rules.py --evaluate 02161234567` |
| Counters | `GET /api/v1/metrics` |
| One call | `GET /api/v1/traces/{call-id}` |
| Health | `curl -s http://127.0.0.1:8081/healthz` for the console |
| Active screening data | `curl -s http://127.0.0.1:8082/api/v1/screening` |
| Verdicts by signal | `curl -s http://127.0.0.1:8082/api/v1/metrics` — the `counters` object holds `verdict.allow` / `verdict.reject`, `screen.block_list` / `screen.rate_window` / `screen.reputation` and `reject.sip_608_undeclared` |
| One screened call | `GET /api/v1/traces/{call-id}` on 8082 — the `verdict` event carries the signal, the score, the calls in window, the matched list entry and whether the INVITE declared `sip.608` |

To watch the screening flow in the console, point it at the second instance:
`AS_INTERNAL_API_URL=http://127.0.0.1:8082 make console`. The page renders either instance,
and says which one it is displaying: the **instance** chip in the status bar, the browser
title and the label of the AS node in the topology view all come from the `instance` field
the AS reports on `/healthz` (`number-translation` or `anti-fraud`), never from the port. The
Screening view shows the lists and parameters, the trace shows the verdict, and the
statistics view shows the verdict counters.

## 4. Logs

| Where | Content |
| --- | --- |
| stdout of the `as` process | Structured JSON application log, one object per line |
| stderr of the `as` process | sippy message log (`SipLogger`, `SIPLOG_BEND=stderr` by default) |
| stdout of the `anti-fraud-as` process | Its own structured JSON log (`screening verdict taken` carries the verdict fields) |
| stdout of `console` | uvicorn access log |
| `captures/` | pcap files written by `tools/capture.sh` (gitignored, never committed) |

A log line always carries `timestamp`, `level`, `module`, `call_id`, `direction`, `peer`
and `event`. To follow one call, filter on its Call-ID:

```bash
uv run python -m as_app.main | grep '"call_id": "probe-59745@example.invalid"'
```

Set `LOG_LEVEL=DEBUG` for more detail and `LOG_PAYLOADS=true` only when payloads are
needed — payload logging is off by default (`AGENT.md` section 9).

## 5. Capture traffic

```bash
./tools/capture.sh                # 60 s on the trunk and mock ports
./tools/capture.sh --port 5060    # trunk only
./tools/capture.sh --list
```

## 6. Routine checks

```bash
make lint      # ruff format --check + ruff check + mypy
make test      # unit + integration + e2e
uv lock --check   # the lock file is in sync with pyproject.toml
```
