# Deployment guide

Scope: a local demo on one machine with `docker compose`, and a local process run with
`uv`. There is **no production deployment** in this POC (`AGENT.md` section 2).

## 1. Topology

```text
   +--------------------------------------------------- docker host --------------------+
   |                                                                                    |
   |  s-sbc-mock                       as                            console            |
   |  UAC 127.0.0.1:15060/udp  =====>  127.0.0.1:5060/udp  <==== HTTP 127.0.0.1:8081    |
   |  UAS 127.0.0.1:15061/udp  <====  (originates back to the UAS port)                 |
   |                                                                                    |
   +------------------------------------------------------------------------------------+
```

## 2. Port matrix

| Service | Container | Protocol / port | Host port | Configured by |
| --- | --- | --- | --- | --- |
| `as` | `as` | UDP `5060` (trunk) | `5060` | `SIP_LISTEN_ADDRESS` / `SIP_LISTEN_PORT` |
| `as` | `as` | TCP `8080` (internal API) | `8080` | `INTERNAL_API_ADDRESS` / `INTERNAL_API_PORT` |
| `s-sbc-mock` | `s-sbc-mock` | UDP `15060` (UAC, emulated S-CSCF trigger) | `15060` | `--listen-port - 1` in `MockConfig` |
| `s-sbc-mock` | `s-sbc-mock` | UDP `15061` (UAS, emulated core network) | `15061` | `--listen-port` |
| `console` | `console` | TCP `8081` | `8081` | `--port` |

Test runs allocate UDP ports dynamically, so tests and CI never collide with `5060`
(`AGENT.md` section 11).

## 3. Resource profile

The POC has no capacity target (REQ-NF-009). For orientation only:

| Service | CPU | Memory | Notes |
| --- | --- | --- | --- |
| `as` | < 1 core | ≈ 120 MB | Single-threaded sippy loop plus the interpreter |
| `s-sbc-mock` | < 1 core | ≈ 120 MB | Same stack as the AS |
| `console` | < 1 core | ≈ 150 MB | FastAPI + uvicorn |

## 4. Starting and stopping

### 4.1 Processes (development)

```bash
uv sync                       # install the locked environment
make dev                      # AS only in M0 (mock and console follow in M1/M3)
python -m as_app.main --self-check-only    # configuration and rules check, then exit
```

Stop with `Ctrl-C` (`SIGINT`) or `kill <pid>` (`SIGTERM`); both shut the process down
gracefully.

### 4.2 Compose (demo)

```bash
make docker-up                # docker compose -f deploy/docker-compose.yml up --build
make docker-down              # docker compose -f deploy/docker-compose.yml down
```

## 5. Health checks

| Check | Command | Expected |
| --- | --- | --- |
| AS self-check | `uv run python -m as_app.main --self-check-only` | exit code `0`, log event `startup self-check passed` |
| Internal API | `curl -s http://127.0.0.1:8080/healthz` | `{"status":"ok",...}` (from M3, when the API is served) |
| Console | `curl -s http://127.0.0.1:8081/healthz` | `{"status":"ok","component":"console"}` |
| Trunk reachable | `uv run python tools/sippy_probe.py` | `minimal SipTransactionManager + ED2.loop() stack: OK` |

## 6. Configuration in deployment

All configuration is environment based (`.env.example`). Switching from the mock to a real
S-SBC means changing `SBC_PEER_ADDRESS`, `SBC_PEER_PORT` and `ALLOWED_PEERS` only — no
code change (`AGENT.md` section 8).

## 7. Shutdown behaviour

`SIGTERM` and `SIGINT` request a graceful shutdown. The handlers only set a flag; the
process stops when the loop observes it, then logs `shutdown complete` with the reason and
the configured grace period.
