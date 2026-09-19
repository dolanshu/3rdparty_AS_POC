# Deployment guide

Scope: a local demo on one machine with `docker compose`, and a local process run with
`uv`. There is **no production deployment** in this POC (`AGENT.md` section 2).

## 1. Topology

Local processes (`make dev` / `make mock` / `make console`) all use the loopback:

```text
   +--------------------------------------------------- docker host --------------------+
   |                                                                                    |
   |  s-sbc-mock                       as                            console            |
   |  UAC 127.0.0.1:15060/udp  =====>  127.0.0.1:5060/udp  <==== HTTP 127.0.0.1:8081    |
   |  UAS 127.0.0.1:15061/udp  <====  (originates back to the UAS port)                 |
   |                                                                                    |
   +------------------------------------------------------------------------------------+
```

The **anti-fraud AS** (P8, ADR-0007) is a second, independently runnable AS on the same host
with its own ports, its own data file and its own console feed. It receives the trunk on
`127.0.0.1:5062/udp`; a call it **allows** is relayed to the next hop (`FRAUD_SBC_PEER_*`),
and a call it **rejects** is answered by the AS itself and never leaves it:

```text
   s-sbc-mock-fraud                        anti-fraud-as
   UAC 127.0.0.1:15063/udp  ===========>   127.0.0.1:5062/udp  --allow-->  next hop
   UAS 127.0.0.1:15062/udp  <===========   (a reject is answered here: 608 Rejected)
```

P8 demonstrates the two AS instances **independently**; the chained
`SBC -> anti-fraud -> number translation -> core` topology is P9's.

`docker compose` puts the services on a private trunk network with **fixed** addresses
(`172.28.0.0/24`, declared in `deploy/docker-compose.yml`), so the address each side
advertises in `Via`/`Contact` is stable and routable in both directions — a container can
never reach another container over `127.0.0.1`:

```text
   +--------------------------- compose network as-poc-trunk (172.28.0.0/24) ------------+
   |                                                                                    |
   |  s-sbc-mock                       as                            console            |
   |  UAC 172.28.0.3:15060/udp =====>  172.28.0.2:5060/udp  <==== HTTP as:8080           |
   |  UAS 172.28.0.3:15061/udp <====   (originates back to 172.28.0.3:15061)            |
   |                                                                                    |
   |  s-sbc-mock-fraud                 anti-fraud-as                                    |
   |  UAC 172.28.0.5:15063/udp =====>  172.28.0.4:5062/udp  <==== HTTP anti-fraud-as:8082|
   |  UAS 172.28.0.5:15062/udp <====   (relays an allowed call back; a reject stops here)|
   |                                                                                    |
   +------------------------------------------------------------------------------------+
```

The trunk hop the AS originates to is the one the active **rule set** selects, so the compose
stack reads a dedicated rule set whose catalogue points at the mock:
`config/routing_rules.compose.yaml` (see section 6).

## 2. Port matrix

| Service | Container | Protocol / port | Host port | Configured by |
| --- | --- | --- | --- | --- |
| `as` | `as` | UDP `5060` (trunk) | `5060` | `SIP_LISTEN_ADDRESS` / `SIP_LISTEN_PORT` |
| `as` | `as` | TCP `8080` (internal API) | `8080` | `INTERNAL_API_ADDRESS` / `INTERNAL_API_PORT` |
| `anti-fraud-as` | `anti-fraud-as` | UDP `5062` (trunk) | `5062` | `FRAUD_SIP_LISTEN_ADDRESS` / `FRAUD_SIP_LISTEN_PORT` |
| `anti-fraud-as` | `anti-fraud-as` | TCP `8082` (internal API) | `8082` | `FRAUD_INTERNAL_API_ADDRESS` / `FRAUD_INTERNAL_API_PORT` |
| `s-sbc-mock` | `s-sbc-mock` | UDP `15060` (UAC, emulated S-CSCF trigger) | `15060` | `--listen-port - 1` in `MockConfig` |
| `s-sbc-mock` | `s-sbc-mock` | UDP `15061` (UAS, emulated core network) | `15061` | `--listen-port` |
| `s-sbc-mock-fraud` | `s-sbc-mock-fraud` | UDP `15063` (UAC, emulated S-CSCF trigger) | `15063` | `--trunk-port` |
| `s-sbc-mock-fraud` | `s-sbc-mock-fraud` | UDP `15062` (UAS, emulated core network) | `15062` | `--listen-port` |
| `console` | `console` | TCP `8081` | `8081` | `--port` |

The two AS instances must not share a listen port: `anti-fraud-as` uses `5062`/`8082`
precisely so both can run on one host (the port-collision trap of
`docs/phase2-plan.md` section 6). A collision is caught at startup by the port-availability
self-check and fails fast as `AS-CFG-003`.

Test runs allocate UDP ports dynamically, so tests and CI never collide with `5060`
(`AGENT.md` section 11).

## 3. Resource profile

The POC has no capacity target (REQ-NF-009). For orientation only:

| Service | CPU | Memory | Notes |
| --- | --- | --- | --- |
| `as` | < 1 core | ≈ 120 MB | Single-threaded sippy loop plus the interpreter |
| `anti-fraud-as` | < 1 core | ≈ 130 MB | Same stack; the cross-call window and reputation ledger are bounded in memory |
| `s-sbc-mock` | < 1 core | ≈ 120 MB | Same stack as the AS |
| `s-sbc-mock-fraud` | < 1 core | ≈ 120 MB | A second mock instance dedicated to the anti-fraud AS |
| `console` | < 1 core | ≈ 150 MB | FastAPI + uvicorn |

## 4. Starting and stopping

### 4.1 Processes (development)

```bash
uv sync                       # install the locked environment
make dev                      # AS locally (run make mock and make console in other terminals)
python -m as_app.main --self-check-only    # configuration and rules check, then exit
make fraud                    # anti-fraud AS locally, on 5062 (P8)
python -m anti_fraud_as.main --self-check-only   # its configuration and Screening data check
```

Stop with `Ctrl-C` (`SIGINT`) or `kill <pid>` (`SIGTERM`); both shut the process down
gracefully. Every timer the process armed is cancelled from its own stop path before
sippy's transaction manager shuts down (P8a).

### 4.2 Compose (demo)

```bash
make docker-up                # docker compose -f deploy/docker-compose.yml up --build
make docker-down              # docker compose -f deploy/docker-compose.yml down
```

Detached form, which is what the P1 evidence used:

```bash
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f as
docker compose -f deploy/docker-compose.yml down
```

All three services come up on their own; the mock places its default `office-to-mobile` call
(`+86216180001` → `+8613800138000`) about half a second after it starts, so the AS log shows a
complete call without any further command. `docker compose down` removes the containers and
the `as-poc-trunk` network; the stack defines no volumes.

#### Package index at build time

The image build talks to a package index in two places: `pip install uv` (reads
`PIP_INDEX_URL`) and `uv sync` (reads `UV_DEFAULT_INDEX`; uv deliberately ignores
`PIP_INDEX_URL` and `pip.conf`). Both are **build arguments whose default is public PyPI**, so
CI and a normal checkout are unaffected:

```bash
# Canonical build: public PyPI, and `uv sync --frozen` verifies the committed lock.
docker compose -f deploy/docker-compose.yml build

# Build behind a mirror, or on a link too slow for PyPI. One variable drives both tools:
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  docker compose -f deploy/docker-compose.yml build
```

Why an index override changes the lock rule: the wheel URLs recorded in `uv.lock` point at
`files.pythonhosted.org`, and `uv sync --frozen` downloads exactly those URLs — it does **not**
substitute the configured index (verified with uv 0.12.15: a sync whose index was unreachable
still fetched those URLs). So when `PIP_INDEX_URL` is not the public default the Dockerfiles
let uv re-resolve against the configured index. That is a build-time decision only: it rewrites
`uv.lock` *inside the image* and keeps every pinned version (same 50 packages, same versions —
only the registry URL changes). The committed `uv.lock` is never touched by a build and keeps
referencing public PyPI, so CI, `uv lock --check` and other machines are unaffected. When
`PIP_INDEX_URL` *is* the public default (CI, a reviewer's checkout) the Dockerfiles still run
`uv sync --frozen`, so a stale lock fails the build exactly as before.

## 5. Health checks

| Check | Command | Expected |
| --- | --- | --- |
| AS self-check | `uv run python -m as_app.main --self-check-only` | exit code `0`, log event `startup self-check passed` |
| Anti-fraud self-check | `uv run python -m anti_fraud_as.main --self-check-only` | exit code `0`, log event `startup self-check passed` |
| Anti-fraud Internal API | `curl -s http://127.0.0.1:8082/healthz` | `{"status":"ok","screening_data_loaded":true,...}` |
| Anti-fraud screening data | `curl -s http://127.0.0.1:8082/api/v1/screening` | the block/allow lists and the window/reputation parameters |
| Anti-fraud screening flow | `make demo-fraud` | one call allowed and relayed, one answered `608 Rejected` |
| Internal API | `curl -s http://127.0.0.1:8080/healthz` | `{"status":"ok",...}` |
| Console | `curl -s http://127.0.0.1:8081/healthz` | `{"status":"ok","component":"console"}` |
| Trunk reachable | `uv run python tools/sippy_probe.py` | `minimal SipTransactionManager + ED2.loop() stack: OK` |
| Compose stack | `docker compose -f deploy/docker-compose.yml ps` | `as`, `s-sbc-mock` and `console` all `Up` |
| Call completed | `curl -s http://127.0.0.1:8080/api/v1/metrics` | `calls_total` ≥ 1, `calls_by_disposition` has `completed`, `rule_hits` has the matched rule |

## 6. Configuration in deployment

All configuration is environment based (`.env.example`). Switching from the mock to a real
S-SBC means changing `SBC_PEER_ADDRESS`, `SBC_PEER_PORT`, `ALLOWED_PEERS` and the addresses in
the active rule set — no code change (`AGENT.md` section 8).

**The rule set carries the trunk addresses.** The AS originates the second leg to the hop the
*rule set* selects: the routing engine resolves `action.next_hops` against the `next_hops`
catalogue in the rules file. `SBC_PEER_ADDRESS`/`SBC_PEER_PORT` describe the peer for the
startup self-check and for logging; they do not rewrite that catalogue. Two rule sets ship
with the POC:

| Rule set | Next hops | Used by |
| --- | --- | --- |
| `config/routing_rules.yaml` | `127.0.0.1:15061` … `15066` | local runs (`make dev` / `make mock`, the tests, `make demo`) |
| `config/routing_rules.compose.yaml` | `172.28.0.3:15061` … `15066` | the compose stack (`RULES_FILE` in `deploy/docker-compose.yml`) |

They are the same 17 rules with the same priorities, hop names, ports and translation
behaviour; only the catalogue addresses differ. `config/routing_rules.yaml` is the source of
truth for the rule data and the compose file is its deployment variant — keep them in step
(the duplication is registered in `docs/production-gaps.md`).

Compose service configuration (the values are in `deploy/docker-compose.yml`):

| Service | Environment |
| --- | --- |
| `as` | `SIP_LISTEN_ADDRESS=172.28.0.2`, `SIP_LISTEN_PORT=5060`, `SBC_PEER_ADDRESS=172.28.0.3`, `SBC_PEER_PORT=15061`, `ALLOWED_PEERS=172.28.0.3`, `RULES_FILE=config/routing_rules.compose.yaml`, `INTERNAL_API_ADDRESS=0.0.0.0`, `INTERNAL_API_PORT=8080`, `LOG_STRUCTURED=true` |
| `anti-fraud-as` | `FRAUD_SIP_LISTEN_ADDRESS=172.28.0.4`, `FRAUD_SIP_LISTEN_PORT=5062`, `FRAUD_SBC_PEER_ADDRESS=172.28.0.5`, `FRAUD_SBC_PEER_PORT=15062`, `FRAUD_ALLOWED_PEERS=172.28.0.5`, `FRAUD_SCREENING_FILE=config/caller_screening.yaml`, `FRAUD_INTERNAL_API_ADDRESS=0.0.0.0`, `FRAUD_INTERNAL_API_PORT=8082` |
| `s-sbc-mock` | command line: `--listen-address 172.28.0.3 --listen-port 15061 --as-address 172.28.0.2 --as-port 5060` |
| `s-sbc-mock-fraud` | command line: `--listen-address 172.28.0.5 --listen-port 15062 --trunk-port 15063 --as-address 172.28.0.4 --as-port 5062` (places one allowed and one blocked call on startup) |
| `console` | `AS_INTERNAL_API_URL=http://as:8080` — set it to `http://anti-fraud-as:8082` to watch the screening flow instead |

**The anti-fraud AS has no rule set.** Its screening data
(`config/caller_screening.yaml`) carries block/allow lists, the reputation parameters and
the call-rate window parameters, and deliberately **no addresses**: the next hop comes from
`FRAUD_SBC_PEER_*`, so there is no second copy of an address to keep in step (the
rule-file-drift trap of `docs/phase2-plan.md` section 6). Switching that AS from the mock to
a real S-SBC is therefore a change of `FRAUD_SBC_PEER_*` and `FRAUD_ALLOWED_PEERS` only.

## 7. Shutdown behaviour

`SIGTERM` and `SIGINT` request a graceful shutdown. The handlers only set a flag; the
process stops when the loop observes it, then logs `shutdown complete` with the reason and
the configured grace period.
