# Runbook

Routine operations for the POC. Every command is run from the repository root unless
stated otherwise.

## 1. Start and stop

| Action | Command |
| --- | --- |
| Sync the environment | `uv sync` |
| Start the AS | `make dev` (or `uv run python -m as_app.main`) |
| Start the mock | `make mock` (places the default call on startup) |
| Start the console | `make console` (console UI on 127.0.0.1:8081) |
| Start everything with compose | `make docker-up` |
| Stop everything | `make docker-down` |
| Stop a foreground process | `Ctrl-C` — expect the `shutdown complete` log line |

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

## 3. Inspect state

| What | How |
| --- | --- |
| Active rule set | `uv run python tools/show_rules.py` |
| Decision for one number | `uv run python tools/show_rules.py --evaluate 02161234567` |
| Counters | `GET /api/v1/metrics` |
| One call | `GET /api/v1/traces/{call-id}` |
| Health | `curl -s http://127.0.0.1:8081/healthz` for the console |

## 4. Logs

| Where | Content |
| --- | --- |
| stdout of the `as` process | Structured JSON application log, one object per line |
| stderr of the `as` process | sippy message log (`SipLogger`, `SIPLOG_BEND=stderr` by default) |
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
