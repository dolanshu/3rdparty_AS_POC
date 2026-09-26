# 3rd-party AS POC

A proof of concept of a **third-party IMS/SIP Application Server (B2BUA)** that lives
outside the operator's network and is reached over a SIP trunk from the operator's
Service-SBC. Two use cases, each its own process: **number translation and intelligent
routing** for an enterprise, and an **anti-fraud screen** that inspects the calling party
and answers unwanted calls with `608 Rejected` (RFC 8688).
**Signalling only** — no media, no RTP.

Read `AGENT.md` first: it defines the delivery standards, the layout and the rules of
engagement for this repository.

[![CI](https://github.com/dolanshu/3rdparty_AS_POC/actions/workflows/ci.yml/badge.svg)](https://github.com/dolanshu/3rdparty_AS_POC/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10-blue)
![sippy](https://img.shields.io/badge/sippy-2.4.2-orange)
![Licence](https://img.shields.io/badge/licence-Apache--2.0-green)

## Position

```text
        operator IMS (mocked)                         SIP trunk              us
 +-------------------------------+                                          +----------------------+
 |  S-CSCF ---ISC--- S-SBC       |  forward INVITE (Route→S-SBC)  =======> | 3rd-party AS (B2BUA)|
 |                               |  <======== translated INVITE ========= |  UAS trunk / UAC out |
 +-------------------------------+              UDP / 5060                 +----------------------+
      (mock: forward @15060, return @15061)                                 (this repository)
```

- We implement the **external AS** — the **only B2BUA** in the path. The operator S-CSCF
  and S-SBC are **not** B2BUAs; the local mock plays both sides of the S-SBC (forward the
  trunk INVITE on `:15060`, receive the AS-originated INVITE back on `:15061`).
- On the trunk leg the AS is a **UAS** (`SIP_LISTEN_PORT`, default `5060`). On the outbound
  leg it is a **UAC** with a new `Call-ID`, sending the translated INVITE to the **top
  `Route`** the S-SBC inserted — back through the same S-SBC into the IMS, not directly to
  the core.
- Redirect mode (`302`) is **not** implemented.
- The **anti-fraud AS** is a second, separate process: it inspects the **calling** party and
  either relays the INVITE unchanged or answers `608 Rejected` (RFC 8688). Its reject path is
  **UAS only** — it originates no second leg — which is the documented deviation from
  "B2BUA only", limited to that path (`REQ-F-021`).
- Headers and SDP are **passed through verbatim**; only the Request-URI and the number
  format are rewritten, and only by the number-translation AS.
- Routing rules and screening data are **declarative data** under `config/`, read-only on
  the console.

## Quickstart

```bash
# Clone both repositories side by side: the platform library first, then this one.
git clone https://github.com/dolanshu/as_platform.git        # the platform library (sibling checkout)
git clone https://github.com/dolanshu/3rdparty_AS_POC.git    # this repository
cd 3rdparty_AS_POC
pip install uv          # uv 0.12.15 is what the toolchain was verified with
uv sync                 # creates .venv from the committed uv.lock and links ../as_platform

make lint               # ruff format --check + ruff check + mypy
make test               # unit + integration + e2e
make demo               # places a real call and narrates the translation (see below)
make demo-fraud         # screens two real calls: one allowed, one answered 608 Rejected
make demo-chained       # iFC chain: S-CSCF#1 -> S-SBC -> anti-fraud -> S-SBC -> S-CSCF#2 -> S-SBC -> translation -> S-SBC -> S-CSCF -> P-CSCF -> UAS
```

`uv sync` resolves the `as-platform` dependency from `../as_platform` (a `path` source with
`editable = true`, ADR-0009 decision 6), so the two directories must be siblings; a checkout
of this repository alone does not resolve it.

Fallback without `uv` (maintainer-approved): `python3 -m venv .venv`, activate it, then
`pip install -e ../as_platform` (the sibling library that `uv` links through the `path`
source) followed by `pip install sippy==2.4.2 pydantic pydantic-settings pyyaml pytest ruff
mypy fastapi uvicorn`.

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

The image build also needs a **package** index (for `pip install uv` and `uv sync`), separate
from the registry mirror. Both tools take it from a build argument that defaults to public
PyPI, so no mirror is baked into the repository and the committed `uv.lock` is never rewritten
by a build:

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  docker compose -f deploy/docker-compose.yml build
```

See `docs/operations/deployment.md` section 4.2 for what that build argument does and why a
non-default index changes the lock rule.

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

[3/5] next-hop side (S-SBC return, after translation)
next-hop INVITE : INVITE sip:013800138000@127.0.0.1:45644 SIP/2.0
```

It writes nothing, so it is safe to run repeatedly; `make capture` is the variant that
stores the messages as samples in `docs/specs/message-samples/`. Dial another number with
`uv run python tools/demo_call.py --called <number>`; a rejected call exits non-zero
because the tool reports whether the call was answered. The narrated run-through for
reviewers is `docs/demo-script.md`, and the rule table is still available with
`make rules`.

**`make demo-fraud` runs the anti-fraud AS on its own ports.** It places two real calls
through the screening AS — one from a caller the screening data allows, one from a caller on
the block list — and prints the verdict, the deciding signal, the reputation and the call
count for each:

```text
[1/2] call allowed and relayed
verdict      : allow
signal       : none
reason       : no screening signal rejected the call
final status : 200
[2/2] call rejected with 608
verdict      : reject
signal       : block_list
list entry   : BL-0001
final status : 608
second leg   : none - the AS answered from the UAS side (RFC 8688, no Call-Info)
```

The rejected call is answered by the AS itself and never reaches the core network: the
reject path is UAS behaviour and originates no second leg. Nothing is written to the
repository; the standalone process is `make fraud`.

**`make demo-chained` runs both AS instances via an iFC orchestrator mock (ADR-0014).** AS-1
and AS-2 never talk directly; iFC #2 fires when AS-1's outbound INVITE is 透传 to the
orchestrator. The terminating UAS is reached through P-CSCF, not the S-SBC return port:

```text
[1/2] allowed call relayed through both AS instances
AS-1 verdict       : allow
AS-2 rule          : R-MOB-CM-40
terminating called : 013800138000
distinct Call-IDs  : 4
ICID preserved     : True
[2/2] rejected call short-circuits at AS-1
final status       : 608
AS-2 calls seen    : 0
```

Every leg derives its own dialog `Call-ID`, so the four AS-leg values differ (`X`,
`X-b2b_1`, `Z`, `Z-b2b_1`) and cross-AS correlation on `Call-ID` is impossible — the `P-Charging-Vector` ICID is on the wire and is
preserved, but no observability surface is keyed on it (a registered gap). The demo is a
guard: it exits non-zero if any of those properties fails. It writes nothing.

The console renders **either** AS instance. Each process reports a stable instance identity
on `/healthz` (`number-translation`, `anti-fraud`), which the page shows in its title, in the
status bar and as the label of the AS node in the topology view — so it is never ambiguous
which instance is on screen. Point it at the second one with
`AS_INTERNAL_API_URL=http://127.0.0.1:8082 make console`.

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
| `SBC_PEER_ADDRESS` / `SBC_PEER_PORT` | `127.0.0.1` / `15061` | fallback next hop (mock or real S-SBC return side) when the trunk INVITE carries no top `Route`; also the peer the startup self-check reports. A routed call takes its wire destination from that `Route` and its hop from the rule catalogue (`127.0.0.1:5061` in `config/routing_rules.yaml`) |
| `ALLOWED_PEERS` | `127.0.0.1` | source addresses accepted on the trunk |
| `RULES_FILE` | `config/routing_rules.yaml` | routing rules |
| `INTERNAL_API_ADDRESS` / `INTERNAL_API_PORT` | `127.0.0.1` / `8080` | how the console reaches the AS |
| `FRAUD_SIP_LISTEN_ADDRESS` / `FRAUD_SIP_LISTEN_PORT` | `127.0.0.1` / `5062` | where the **anti-fraud AS** receives the trunk (5062, not 5060, so both instances run on one host) |
| `FRAUD_SBC_PEER_ADDRESS` / `FRAUD_SBC_PEER_PORT` | `127.0.0.1` / `15062` | fallback next hop when the trunk has no `Route`; allow path uses top `Route` → S-SBC return |
| `FRAUD_ALLOWED_PEERS` | `127.0.0.1` | source addresses accepted on the anti-fraud trunk |
| `FRAUD_SCREENING_FILE` | `config/caller_screening.yaml` | screening data: block/allow lists, window and reputation parameters |
| `FRAUD_INTERNAL_API_ADDRESS` / `FRAUD_INTERNAL_API_PORT` | `127.0.0.1` / `8082` | how the console reaches the anti-fraud AS |
| `LOG_LEVEL`, `LOG_STRUCTURED`, `LOG_PAYLOADS` | `INFO` / `true` / `false` | logging (shared by both AS processes) |

Switching from the mock to a real S-SBC is a change of `SBC_PEER_*`, `ALLOWED_PEERS` and the
next-hop addresses in the active rule set: the AS originates the second leg to the hop the
rule set selects. Full reference: `docs/architecture/lld.md` section 6 and
`docs/operations/deployment.md` section 6.

## Repository tour

```text
AGENT.md                 rules of engagement, delivery standards, milestones
config/                  routing rules and screening data (data, hot reloaded)
deploy/                  docker-compose.yml + one Dockerfile per service
docs/                    documentation set (see the index below)
../as_platform/          the platform library (separate repository, checked out beside this one)
  src/as_platform/       the shared skeleton both AS instances build on: observability,
                         sip_adapter, hop, error mechanism, bootstrap plumbing, internal-API
                         shell, controller base, seams (ADR-0009)
src/as_app/              the third-party AS (sippy application)
  main.py                entry point: AsStack over the library's BaseAsStack
  bootstrap.py           AsSettings, startup self-check; plumbing re-exported from the library
  call_controller.py     Call Control Logic — the business hook (decide() over the library base)
  sip_adapter.py         re-export facade over the library's sippy adapter
  errors.py              the AS-RULE-* / AS-ROUTE-* family over the library's error mechanism
  routing/rules.py       YAML rule model, loading, reload detection
  routing/engine.py      pure translation and routing decisions
  observability/         re-export facades over the library's logging, counters and tracing
  internal_api.py        routes and payloads over the library's internal-API shell
src/anti_fraud_as/       the second AS: caller screening, 608 Rejected (ADR-0007)
  main.py                entry point: FraudAsStack over the library's BaseAsStack
  call_controller.py     the verdict seam, allow relay, UAS-only 608 reject
  screening.py           pure verdict function (no sockets, no clock)
  caller_state.py        process-level call-rate window and reputation decay
  screening_data.py      screening data model, validation, reload
  internal_api.py        routes and payloads over the library's internal-API shell
src/console/             FastAPI + plain HTML/CSS/JS, separate process
src/s_sbc_mock/          mock S-SBC: forward side (INVITE + Route) + return side
tests/{unit,integration,e2e}/
tools/                   sippy probe, 608 probe, rule viewer, capture helper, demos
```

Rules of the layout: `src/as_app` never imports from `src/s_sbc_mock`; routing decisions
live in `routing/engine.py` as pure functions; sippy interaction is confined to the sip
adapter and the call controllers. The shared skeleton of the two AS packages now lives in
the **platform library** (`../as_platform`, ADR-0009): both `src/as_app` and
`src/anti_fraud_as` build on it, and the library never imports either — they are two
concrete AS instances, not a framework (ADR-0007).

## Non-goals

Explicitly out of scope; each item is registered in `docs/production-gaps.md`:

- No real IMS core (no S-CSCF, I-CSCF, HSS, MRF, real S-SBC).
- No media: no RTP, no transcoding, no DTMF, no MRF.
- No published performance or capacity figures and no benchmarking claims. (A capacity
  harness exists to find where the boundary is; it reports constraints, never a headline
  number — `AGENT.md` §2.)
- No production HA, multi-tenancy or auditing.
- No charging (no CDRs, no RADIUS).
- No production-grade transport on the trunk; demo stack is UDP-only. The platform library (`../as_platform`, ADR-0010) ships a pluggable `Transport` seam with `TlsTransport` behind it — TCP is still out of scope, SIP Digest is still out of scope.
- No production deployment beyond a local `docker compose` demo.

## Documentation index

| Document | Contents |
| --- | --- |
| `docs/README.md` | navigation by audience |
| `docs/requirements/functional-and-nonfunctional.md` | `REQ-F-*` / `REQ-NF-*` capability list |
| `docs/architecture/hld.md` | context, deployment and interface views, message flows |
| `docs/architecture/lld.md` | modules, data structures, state machines, error codes, log fields |
| `docs/architecture/adr/` | ADR-0001 … ADR-0014: 0008 chained topology (historical), 0014 iFC-orchestrated chain mock (P9b), 0009 platform library, 0010 P11 TLS + Redis + harness |
| `../as_platform/` (the platform library) | the shared skeleton both AS instances build on, in its own repository checked out beside this one, with its own gate and its library-standard documents (API reference, integration guide, compatibility matrix) |
| `docs/specs/index.md`, `docs/specs/message-samples/` | normative references and real message samples; the generated samples are gitignored, only the folder `README.md` is tracked |
| `docs/operations/deployment.md` | topology, port matrix, health checks |
| `docs/operations/runbook.md` | start, stop, reload rules and screening data, inspect state |
| `docs/operations/troubleshooting.md` | symptom → cause → action |
| `docs/acceptance/criteria.md` | `ACC-*` items with verification commands |
| `docs/acceptance/report.md` | results and evidence |
| `docs/demo-script.md` | the 5–10 minute narrated demo |
| `docs/glossary.md` | IMS/SIP terminology |
| `docs/production-gaps.md` | every POC shortcut and what production would require |
| `docs/roadmap.md` | milestone status, handover notes, open items — live status board |
| `docs/phase2-plan.md` | Phase 2 (P8 anti-fraud, P9 chained demo, P10 platform extraction, P11 TLS/Redis/harness): decisions, work sequence, acceptance |
| `docs/post-phase2-directions.md` | post-phase2 direction candidates (multi-tenancy, STIR/SHAKEN, HA, …) |

## Development

```bash
make dev          # run the number-translation AS locally
make fraud        # run the anti-fraud AS locally (separate process, port 5062)
make lint         # ruff format --check + ruff check + mypy
make test         # unit + integration + e2e
make demo-fraud   # screen two real calls and narrate the verdicts
make docker-up    # as + anti-fraud-as + s-sbc-mock + s-sbc-mock-fraud + console
```

See `CONTRIBUTING.md` for the working rules, `SECURITY.md` for what is deliberately not
implemented, and `CHANGELOG.md` for the milestone history.

## Licence and notices

Apache-2.0 (`LICENSE`). Third-party notices, including the BSD-2-Clause attribution for
sippy, are in `NOTICE`.


Maintained by Dolan Shu <dolan.d.shu@gmail.com>.
