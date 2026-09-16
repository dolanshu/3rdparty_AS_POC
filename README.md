# 3rd-party AS POC

A proof of concept of a **third-party IMS/SIP Application Server (B2BUA)** that lives
outside the operator's network and is reached over a SIP trunk from the operator's
Service-SBC. It performs number translation and intelligent routing for an enterprise.
**Signalling only** — no media, no RTP.

Read `AGENT.md` first: it defines the delivery standards, the layout and the rules of
engagement for this repository.

[![CI](https://github.com/dolanshu/3rdparty_AS_POC/actions/workflows/ci.yml/badge.svg)](https://github.com/dolanshu/3rdparty_AS_POC/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10-blue)
![sippy](https://img.shields.io/badge/sippy-2.4.2-orange)
![Licence](https://img.shields.io/badge/licence-Apache--2.0-green)

## Position

```text
        operator IMS core                    SIP trunk                  us
 +-------------------------------+                          +----------------------+
 |  S-CSCF ---ISC--- S-SBC       | ======================== | 3rd-party AS (B2BUA)|
 +-------------------------------+        UDP / 5060        +----------------------+
      (mocked: UAC + UAS side)                                  (this repository)
```

- We implement the **external AS**. The S-SBC, the S-CSCF and the core network are
  replaced by a local mock, and every peer address is configuration, so the same code can
  be pointed at a real S-SBC by changing configuration only.
- We are a **B2BUA and only a B2BUA**: terminate the incoming INVITE, translate the
  number, originate a new INVITE back. Redirect mode (`302`) is **not** implemented.
- Headers and SDP are **passed through verbatim**; only the Request-URI and the number
  format are rewritten.
- Routing rules are **declarative data** and read-only on the console.

## Quickstart

```bash
git clone git@github.com:dolanshu/3rdparty_AS_POC.git
cd 3rdparty_AS_POC
pip install uv          # uv 0.12.15 is what the toolchain was verified with
uv sync                 # creates .venv from the committed uv.lock

make lint               # ruff format --check + ruff check + mypy
make test               # unit + integration + e2e
make demo               # places a real call and narrates it (see below)
```

Fallback without `uv` (maintainer-approved): `python3 -m venv .venv`, activate it, then
`pip install sippy==2.4.2 pydantic pydantic-settings pyyaml pytest ruff mypy fastapi
uvicorn`.

### Slow or blocked network (China mirrors)

The default indices live on public PyPI and GitHub, which are slow or blocked from some
networks. The snippet below routes **everything** through domestic mirrors. It does not
change `pyproject.toml`, and the committed `uv.lock` still records the public PyPI so CI
is unaffected.

```bash
# 1) uv package index -> Tsinghua PyPI mirror (fast pip/uv resolution)
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# 2) uv downloads the managed Python (3.10) from python-build-standalone on GitHub ->
#    route it through a GitHub proxy so `uv sync` does not stall on the Python fetch
export UV_PYTHON_DOWNLOAD_URL=https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download

# 3) If uv itself is not installed and `pip` is unavailable, fetch the uv binary via the
#    same proxy (the install script downloads from GitHub directly and would be slow):
curl -LsSf "https://ghproxy.net/https://github.com/astral-sh/uv/releases/download/0.12.15/uv-x86_64-unknown-linux-gnu.tar.gz" -o /tmp/uv.tgz
tar -xzf /tmp/uv.tgz -C /tmp && install -m 0755 /tmp/uv-x86_64-unknown-linux-gnu/uv ~/.local/bin/uv

uv sync                 # Python 3.10 + all deps now download in seconds
```

> **Lock caveat.** Syncing with a mirror rewrites `uv.lock` so every package source points
> at the mirror. Revert it before any commit — `git checkout uv.lock` — so the committed lock
> keeps referencing the public PyPI (CI-safe). The built `.venv` and uv's wheel cache stay
> fast on repeat runs.

For `docker compose` (base image + sippy dependencies pull from Docker Hub), add a registry
mirror to `/etc/docker/daemon.json` and restart the daemon:

```json
{ "registry-mirrors": ["https://docker.m.daocloud.io"] }
```

`docker.m.daocloud.io` was reachable from this environment; if your network blocks it, swap
in another mirror (`https://hub-mirror.c.163.com`, `https://mirror.baidubce.com`,
`https://mirror.ccs.tencentyun.com`).

### Demo

**`make demo` places a real call and narrates it.** It starts the AS and the emulated
S-SBC on loopback, dials `+86216180001` → `+8613800138000`, and prints the routing
decision, the Request-URI before and after number translation, every message on the wire
and the outcome:

```text
[2/5] routing decision
rule        : R-MOB-CM-40
disposition : route
translation : called number -> 013800138000
next hops   : s-sbc-primary -> s-sbc-failover
served by   : s-sbc-primary

[3/5] next-hop side (after translation)
core INVITE : INVITE sip:013800138000@127.0.0.1:45644 SIP/2.0
```

It writes nothing, so it is safe to run repeatedly; `make capture` is the variant that
stores the messages as samples in `docs/specs/message-samples/`. Dial another number with
`uv run python tools/demo_call.py --called <number>`; a rejected call exits non-zero
because the tool reports whether the call was answered. The narrated run-through for
reviewers is `docs/demo-script.md`, and the rule table is still available with
`make rules`.

To verify that the SIP stack really runs:

```bash
make probe      # uv run python tools/sippy_probe.py
```

It starts a minimal `SipTransactionManager` + `ED2.loop()` on loopback, sends one INVITE
and prints the response. Output of the M0 run is recorded in
`docs/acceptance/report.md`.

## Configuration

All configuration is environment based; copy `.env.example` to `.env` and adjust.

| Knob | Default | Purpose |
| --- | --- | --- |
| `SIP_LISTEN_ADDRESS` / `SIP_LISTEN_PORT` | `127.0.0.1` / `5060` | where the AS receives the trunk |
| `SBC_PEER_ADDRESS` / `SBC_PEER_PORT` | `127.0.0.1` / `5061` | next hop (mock or real S-SBC); `.env.example` ships `15061` to match the local mock |
| `ALLOWED_PEERS` | `127.0.0.1` | source addresses accepted on the trunk |
| `RULES_FILE` | `config/routing_rules.yaml` | routing rules |
| `INTERNAL_API_ADDRESS` / `INTERNAL_API_PORT` | `127.0.0.1` / `8080` | how the console reaches the AS |
| `LOG_LEVEL`, `LOG_STRUCTURED`, `LOG_PAYLOADS` | `INFO` / `true` / `false` | logging |

Switching from the mock to a real S-SBC is a change of `SBC_PEER_*` and `ALLOWED_PEERS`
only. Full reference: `docs/architecture/lld.md` section 6.

## Repository tour

```text
AGENT.md                 rules of engagement, delivery standards, milestones
config/                  routing rules (data, hot reloaded)
deploy/                  docker-compose.yml + one Dockerfile per service
docs/                    documentation set (see the index below)
src/as_app/              the third-party AS (sippy application)
  main.py                entry point: settings, self-check, sippy event loop
  bootstrap.py           AsSettings, startup self-check, graceful shutdown
  call_controller.py     Call Control Logic — the business hook
  sip_adapter.py         thin wrapper around sippy primitives
  errors.py              AS-* error model mapped to SIP status codes
  routing/rules.py       YAML rule model, loading, reload detection
  routing/engine.py      pure translation and routing decisions
  observability/         structured logging, counters, per-Call-ID tracing
  internal_api.py        payloads for the console API
src/console/             FastAPI + plain HTML/CSS/JS, separate process
src/s_sbc_mock/          mock S-SBC: UAC (S-CSCF trigger) + UAS (core network)
tests/{unit,integration,e2e}/
tools/                   sippy probe, rule viewer, capture helper
```

Rules of the layout: `src/as_app` never imports from `src/s_sbc_mock`; routing decisions
live in `routing/engine.py` as pure functions; sippy interaction is confined to
`sip_adapter.py` and `call_controller.py`.

## Non-goals

Explicitly out of scope; each item is registered in `docs/production-gaps.md`:

- No real IMS core (no S-CSCF, I-CSCF, HSS, MRF, real S-SBC).
- No media: no RTP, no transcoding, no DTMF, no MRF.
- No performance or capacity work, no benchmarking claims.
- No production HA, multi-tenancy or auditing.
- No charging (no CDRs, no RADIUS).
- No transport beyond UDP: no TCP, no TLS, no SIP Digest.
- No production deployment beyond a local `docker compose` demo.

## Documentation index

| Document | Contents |
| --- | --- |
| `docs/README.md` | navigation by audience |
| `docs/requirements/functional-and-nonfunctional.md` | `REQ-F-*` / `REQ-NF-*` capability list |
| `docs/architecture/hld.md` | context, deployment and interface views, message flows |
| `docs/architecture/lld.md` | modules, data structures, state machines, error codes, log fields |
| `docs/architecture/adr/` | ADR-0001 … ADR-0006 |
| `docs/specs/index.md`, `docs/specs/message-samples/` | normative references and real message samples; the generated samples are gitignored, only the folder `README.md` is tracked |
| `docs/operations/deployment.md` | topology, port matrix, health checks |
| `docs/operations/runbook.md` | start, stop, reload rules, inspect state |
| `docs/operations/troubleshooting.md` | symptom → cause → action |
| `docs/acceptance/criteria.md` | `ACC-*` items with verification commands |
| `docs/acceptance/report.md` | results and evidence |
| `docs/demo-script.md` | the 5–10 minute narrated demo |
| `docs/glossary.md` | IMS/SIP terminology |
| `docs/production-gaps.md` | every POC shortcut and what production would require |
| `docs/roadmap.md` | milestone status, handover notes, open items |

## Development

```bash
make dev          # run the AS locally
make lint         # ruff format --check + ruff check + mypy
make test         # unit + integration + e2e
make docker-up    # as + s-sbc-mock + console
```

See `CONTRIBUTING.md` for the working rules, `SECURITY.md` for what is deliberately not
implemented, and `CHANGELOG.md` for the milestone history.

## Licence and notices

Apache-2.0 (`LICENSE`). Third-party notices, including the BSD-2-Clause attribution for
sippy, are in `NOTICE`.
