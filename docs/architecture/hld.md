# High level design

## 1. Purpose and context

The system under design is a **third-party Application Server (AS)** that lives outside
the operator's IMS network and is reached over a SIP trunk from the operator's
Service-SBC (S-SBC). It performs number translation and intelligent routing for an
enterprise. It is a **B2BUA**: it terminates the incoming INVITE and originates a new
INVITE back towards the S-SBC. It is **signalling only** (ADR-0006).

The S-SBC, the S-CSCF and the core network behind them are **not** part of this system.
They are replaced by a local mock, and every peer address is configuration, so the same
code can be pointed at a real S-SBC by changing configuration only.

```mermaid
graph LR
    subgraph operator["operator IMS core (mocked)"]
        SCSCF["S-CSCF<br/>iFC trigger (ISC)"]
        SSBC["Service-SBC<br/>trunk side"]
    end
    subgraph ours["this repository"]
        AS["3rd-party AS (B2BUA)"]
        MOCK["mock S-SBC<br/>UAC + UAS"]
        CONSOLE["console<br/>separate process"]
    end
    SCSCF -- "ISC / iFC" --> SSBC
    SSBC == "SIP trunk<br/>UDP" ==> AS
    AS -. "internal API<br/>HTTP + WebSocket" .-> CONSOLE
    MOCK -. "stands in for" .-> SSBC
```

## 2. Deployment view

Three processes. The AS and the console are separate on purpose (ADR-0002): sippy's
`ED2.loop()` blocks its thread and must never share it with a web server.

```mermaid
graph TB
    subgraph host["docker compose host"]
        AS["as<br/>UDP 5060 (trunk)<br/>TCP 8080 (internal API)"]
        MOCK["s-sbc-mock<br/>UDP 15060 (UAC)<br/>UDP 15061 (UAS)"]
        CONSOLE["console<br/>TCP 8081"]
    end
    MOCK == "INVITE" ==> AS
    AS == "translated INVITE" ==> MOCK
    CONSOLE -- "HTTP / WS" --> AS
```

| Service | Process | Ports | Purpose |
| --- | --- | --- | --- |
| `as` | `python -m as_app.main` | `5060/udp` trunk, `8080/tcp` internal API | The B2BUA under design |
| `s-sbc-mock` | `python -m s_sbc_mock.main` | `15060/udp` UAC side, `15061/udp` UAS side | Emulates the S-CSCF trigger and the core network |
| `console` | `python -m console.main` | `8081/tcp` | Operations UI, reaches the AS over the internal API |

Ports are configuration; see `docs/operations/deployment.md` for the full port matrix.

## 3. Interface view

| Interface | Direction | Protocol | Notes |
| --- | --- | --- | --- |
| SIP trunk | S-SBC → AS | SIP over UDP (RFC 3261) | Only interface that carries calls; source address verified against `ALLOWED_PEERS` |
| SIP trunk | AS → next hop | SIP over UDP | New INVITE originated by the B2BUA towards `SBC_PEER_*` |
| Internal API | console → AS | HTTP (REST) + WebSocket | `GET /healthz`, `/api/v1/metrics`, `/api/v1/rules`, `/api/v1/traces`, `WS /ws/events` |
| Rules file | operator → AS | YAML file | `config/routing_rules.yaml`, read-only on the console, hot reloaded (ADR-0004) |

## 4. Key message flows

### 4.1 Successful call

```mermaid
sequenceDiagram
    participant UAC as mock UAC (S-CSCF)
    participant AS as 3rd-party AS
    participant UAS as mock UAS (core)
    UAC->>AS: INVITE sip:+8613800138000@as
    AS->>AS: translate +8613800138000 -> 013800138000 (R-MOB-CM-40)
    AS->>UAS: INVITE sip:013800138000@s-sbc-mock
    UAS-->>AS: 100 Trying
    AS-->>UAC: 100 Trying
    UAS-->>AS: 180 Ringing
    AS-->>UAC: 180 Ringing
    UAS-->>AS: 200 OK
    AS-->>UAC: 200 OK
    UAC->>AS: ACK
    AS->>UAS: ACK
    UAC->>AS: BYE
    AS->>UAS: BYE
    UAS-->>AS: 200 OK
    AS-->>UAC: 200 OK
```

### 4.2 Error branches

| Case | Trigger | AS behaviour |
| --- | --- | --- |
| No matching rule | called number matches no enabled rule | `404 Not Found`, error code `AS-ROUTE-001` |
| Policy rejection | rule action `reject` (premium-rate blocklist) | `603 Decline`, error code `AS-ROUTE-002` |
| Caller abandons | `CANCEL` before answer | `487 Request Terminated` on the trunk, outbound leg torn down |
| Unknown peer | source address not in `ALLOWED_PEERS` | `403 Forbidden`, error code `AS-PEER-001` |

## 5. Quality attributes

| Attribute | Approach in this POC |
| --- | --- |
| Testability | Translation and routing are pure functions (`routing/engine.py`); three test layers with dynamically allocated UDP ports |
| Observability | Structured JSON log lines keyed by Call-ID, counters, per-Call-ID trace, operations console |
| Operability | Startup self-check and fail-fast; configuration from the environment; graceful shutdown |
| Changeability | Routing policy is data, not code (ADR-0004); switching mock ↔ real S-SBC is configuration only |
| Security (baseline) | Source address allowlist, no secrets committed, payload logging off by default. TLS and Digest are **not** implemented — see `docs/production-gaps.md` |
| Performance | Explicitly out of scope (REQ-NF-009): no throughput or latency target |

## 6. Constraints

- Python 3.10, sippy 2.4.2 pinned (`AGENT.md` section 6, ADR-0001).
- sippy's `ED2.loop()` blocks; no blocking operation inside sippy callbacks.
- UDP only (ADR-0003). No media (ADR-0006).
- Console without third-party front-end libraries and without a build step.
- The AS must never import from the mock (`AGENT.md` section 5).

## 7. Design decisions

| ADR | Decision |
| --- | --- |
| 0001 | Use sippy as the SIP stack and B2BUA framework |
| 0002 | Run the console as a separate process, talking over an internal API |
| 0003 | UDP only |
| 0004 | Declarative YAML routing rules with reload |
| 0005 | Mock the S-SBC on the same stack as the AS |
| 0006 | Signalling only, no media |
| 0007 | Anti-fraud AS: use case, `608 Rejected` semantics and cross-call state ownership |
| 0008 | Chained AS topology: configuration-only chaining and `Call-ID` preservation across two B2BUAs |

## 8. The second AS instance — anti-fraud (P8)

`docs/phase2-plan.md` D2 puts a second AS use case before any platform work, and D6 makes
it a **separate, independently runnable process**. This section adds that second instance to
the system context, the deployment view and the interface view. It extends the views above
rather than replacing them: the number-translation AS and its console are unchanged.

### 8.1 System context

The anti-fraud AS is a second B2BUA on the same trunk pattern, but it inspects the
**calling** party and returns a **verdict** instead of rewriting the called number
(`docs/phase2-plan.md` D4, ADR-0007). It is reached over a SIP trunk from the same
S-SBC/mock and relays the allowed call back to it.

```mermaid
graph LR
    subgraph operator["operator IMS core (mocked)"]
        SSBC["Service-SBC<br/>trunk side"]
    end
    subgraph ours["this repository"]
        AS["3rd-party AS (B2BUA)<br/>number translation"]
        FRAUD["anti-fraud AS (B2BUA / UAS)<br/>screening verdict"]
        MOCK["mock S-SBC<br/>UAC + UAS"]
        CONSOLE["console<br/>separate process"]
    end
    SSBC == "SIP trunk<br/>UDP" ==> FRAUD
    SSBC == "SIP trunk<br/>UDP" ==> AS
    FRAUD -. "internal API<br/>HTTP + WebSocket" .-> CONSOLE
    AS -. "internal API<br/>HTTP + WebSocket" .-> CONSOLE
    MOCK -. "stands in for" .-> SSBC
```

The two AS instances are **independent**: neither imports the other, each has its own
configuration, data file, ports and lifecycle. The chained topology
(`SBC → anti-fraud AS → number-translation AS → core`) is P9's, not P8's; D6 builds it
before the platform work precisely to expose the friction between the two instances
(section 9).

### 8.2 Deployment view

**Five processes now**: the two AS instances, the two mocks and the console. The anti-fraud
AS is a separate process for the same reason as the number-translation AS (ADR-0002):
sippy's `ED2.loop()` blocks, so its internal API runs in its own process and on its own port,
and the two AS instances must not share a listen port (D6, and the port-collision trap in
`docs/phase2-plan.md` section 6). Each AS has its **own mock** so either instance can be
demonstrated on its own; P8 does not chain them (that is P9).

```mermaid
graph TB
    subgraph host["docker compose host"]
        AS["as<br/>UDP 5060 (trunk)<br/>TCP 8080 (internal API)"]
        FRAUD["anti-fraud-as<br/>UDP 5062 (trunk)<br/>TCP 8082 (internal API)"]
        MOCK["s-sbc-mock<br/>UDP 15060 (UAC)<br/>UDP 15061 (UAS)"]
        MOCKF["s-sbc-mock-fraud<br/>UDP 15063 (UAC)<br/>UDP 15062 (UAS)"]
        CONSOLE["console<br/>TCP 8081"]
    end
    MOCK == "INVITE" ==> AS
    MOCKF == "INVITE" ==> FRAUD
    AS == "translated INVITE" ==> MOCK
    FRAUD == "relayed INVITE (allow)" ==> MOCKF
    CONSOLE -- "HTTP / WS" --> AS
    CONSOLE -- "HTTP / WS" --> FRAUD
```

| Service | Process | Ports | Purpose |
| --- | --- | --- | --- |
| `as` | `python -m as_app.main` | `5060/udp` trunk, `8080/tcp` internal API | Number translation and routing (Phase 1) |
| `anti-fraud-as` | `python -m anti_fraud_as.main` | `5062/udp` trunk, `8082/tcp` internal API | Caller screening: allow or `608 Rejected` (P8) |
| `s-sbc-mock` | `python -m s_sbc_mock.main` | `15060/udp` UAC side, `15061/udp` UAS side | Emulates the S-CSCF trigger and the core network for `as` |
| `s-sbc-mock-fraud` | `python -m s_sbc_mock.main` | `15063/udp` UAC side, `15062/udp` UAS side | Same mock, dedicated to `anti-fraud-as` |
| `console` | `python -m console.main` | `8081/tcp` | Operations UI, reaches **either** AS over its internal API and reports which instance it is displaying |

Every port is configuration and **no default silently points at a real network**. The
distinct listen port (`5062`) is a deliberate default: without it, running both instances
locally collides on `5060`, which is the trap recorded in `docs/phase2-plan.md` section 6.
The full port matrix is in `docs/operations/deployment.md` section 2.

### 8.3 Interface view

| Interface | Direction | Protocol | Notes |
| --- | --- | --- | --- |
| SIP trunk (reject) | S-SBC → anti-fraud AS → S-SBC | SIP over UDP | The AS terminates the INVITE and answers it **from the UAS side only**: `608 Rejected`, no second leg, no `Call-Info` (ADR-0007). The answer is **unconditional** — it does not depend on the UAC's `Feature-Caps` declaration, which only bears on RFC 8688 section 3.4's announcement obligation and is recorded as `sip_608_declared` |
| SIP trunk (allow) | S-SBC → anti-fraud AS → S-SBC | SIP over UDP | The AS relays the INVITE as a B2BUA: the Request-URI and the SDP body are kept and the **pass-through header set** is copied, **no header is added**, and the response is relayed back. `Feature-Caps` is **not** in that set, so the `sip.608` declaration does not cross the AS (ADR-0007 decision 6) |
| Calling identity | inside the INVITE | `P-Asserted-Identity` | The screening input: the AS inspects the *calling* party, not the called number (D4) |
| Internal API | console → anti-fraud AS | HTTP (REST) + WebSocket | `GET /healthz` (answers the stable **instance identity** the console renders), `/api/v1/metrics`, `/api/v1/screening`, `/api/v1/traces`, `WS /ws/events` |
| Screening data file | operator → anti-fraud AS | YAML file | `config/caller_screening.yaml`: block/allow lists, reputation seed, window parameters. Read-only; validated on load and hot reloaded like the routing rules (ADR-0004 pattern) |

The `608` reject path and the allow path are the two external outcomes, and both are
covered by the flows below.

### 8.4 Key message flows

**Allow path — verdict allow, then a relayed call.** The screening decision is taken before
the outbound leg exists; once the verdict is *allow*, the call is an ordinary B2BUA relay
with nothing added to the wire.

```mermaid
sequenceDiagram
    participant UAC as mock UAC (S-SBC)
    participant FAS as anti-fraud AS
    participant UAS as mock UAS (core)
    UAC->>FAS: INVITE (From/P-Asserted-Identity = caller)
    FAS->>FAS: screen(caller) -> allow (reputation, window, lists)
    Note over FAS: no header added, Request-URI unchanged
    FAS->>UAS: INVITE (relayed verbatim)
    UAS-->>FAS: 100 Trying
    FAS-->>UAC: 100 Trying
    UAS-->>FAS: 180 Ringing
    FAS-->>UAC: 180 Ringing
    UAS-->>FAS: 200 OK
    FAS-->>UAC: 200 OK
    UAC->>FAS: ACK
    FAS->>UAS: ACK
    UAC->>FAS: BYE
    FAS->>UAS: BYE
    UAS-->>FAS: 200 OK
    FAS-->>UAC: 200 OK
```

**Reject path — UAS-only answer, no second leg.** The AS terminates the INVITE and answers
it from the answering leg. No `INVITE` is ever originated towards the core, so the core side
of the mock sees nothing.

```text
UAC (S-SBC)                         anti-fraud AS                         core
    |                                    |                                 |
    |--- INVITE ------------------------>|                                 |
    |                                    | screen(caller) -> reject        |
    |                                    |   reason: block_list /          |
    |                                    |           rate_window /         |
    |                                    |           reputation            |
    |<-- 100 Trying ---------------------|                                 |
    |<-- 608 Rejected -------------------|   CCEventFail((608,"Rejected"))  |
    |                                    |   no Call-Info, no media         |
    |--- ACK --------------------------->|                                 |
    |                                    |                                 |
    |          (no INVITE is ever sent towards the core side)              |
```

The reject is emitted exactly as the two-leg path emits its `404`/`603`: a `CCEventFail`
carrying `(608, "Rejected", None)` on the answering leg. The observable difference is that
the originating leg (`uaO`) is **never created**, so the controller must tolerate a call
with a single leg for its whole lifetime (`docs/architecture/lld.md` section 9).

**The reject does not branch on the declaration.** RFC 8688 section 3.4 requires the `608`
to be forwarded as the final response to the INVITE and places the announcement duty on the
element that inserts `sip.608` (ADR-0007 decision 5). The presence or absence of
`Feature-Caps: *;+sip.608` therefore selects no status code: the AS always answers `608`,
and an absent declaration only means the announcement obligation is unmet. Because that
distinction has to be visible, every screened INVITE carries the declaration state
(`sip_608_declared`) in the trace and the structured log.

## 9. The chained topology (P9)

`docs/phase2-plan.md` D6 puts the two AS instances **in series** before the platform work:
`SBC → AS-1 (anti-fraud) → AS-2 (number translation) → core`. This section adds the chained
deployment view, the interface view and the key flows. It extends the views above rather
than replacing them: the two instances, their consoles and their independent demos are
unchanged (section 8), and the chain is wired **by configuration only** — no code change, no
iFC emulation in the mock, and neither AS imports the other (ADR-0008 decision 1).

### 9.1 System context

The S-CSCF trigger reaches AS-1, whose **allowed** INVITE is relayed to AS-2 instead of back
to the core; AS-2 translates the number and originates the call towards the core. A `608`
reject at AS-1 ends the call there.

```mermaid
graph LR
    subgraph operator["operator IMS core (mocked)"]
        SSBC["Service-SBC / S-CSCF trigger<br/>mock UAC"]
        CORE["core network<br/>mock UAS"]
    end
    subgraph ours["this repository"]
        FRAUD["AS-1 anti-fraud (B2BUA / UAS)<br/>screening verdict"]
        AS["AS-2 number translation (B2BUA)<br/>translate + route"]
        CONSOLE["console<br/>separate process"]
    end
    SSBC == "SIP trunk<br/>UDP" ==> FRAUD
    FRAUD == "allowed INVITE<br/>UDP" ==> AS
    AS == "translated INVITE<br/>UDP" ==> CORE
    FRAUD -. "608 reject ends the call here" .-> SSBC
    FRAUD -. "internal API" .-> CONSOLE
    AS -. "internal API" .-> CONSOLE
```

The chain adds **no** new node type and no new process kind: it is the two existing B2BUAs
connected trunk-to-trunk, with the mock playing the S-CSCF on one side and the core on the
other.

### 9.2 Deployment view

In production the chain is the **three processes** of sections 2 and 8.2 wired in series — the
anti-fraud AS, the number-translation AS and the mock that plays either end — plus the
console. Each AS's next hop is pointed at the next instance, and **no new port is needed**:
`5060` and `5062` already differ precisely so both instances run on one host
(`docs/phase2-plan.md` section 6, "Port collision"). The demo runs the same chain on
dynamically allocated ports (ADR-0008 decision 6).

```mermaid
graph TB
    subgraph host["one host"]
        MOCK["s-sbc-mock<br/>UDP 15060 (UAC)<br/>UDP 15061 (UAS)"]
        FRAUD["anti-fraud-as (AS-1)<br/>UDP 5062 (trunk)<br/>TCP 8082 (internal API)"]
        AS["as (AS-2)<br/>UDP 5060 (trunk)<br/>TCP 8080 (internal API)"]
        CONSOLE["console<br/>TCP 8081"]
    end
    MOCK == "INVITE" ==> FRAUD
    FRAUD == "allowed INVITE" ==> AS
    AS == "translated INVITE" ==> MOCK
    CONSOLE -- "HTTP / WS" --> FRAUD
    CONSOLE -- "HTTP / WS" --> AS
```

| Service | Process | Ports | Role in the chain |
| --- | --- | --- | --- |
| `anti-fraud-as` (AS-1) | `python -m anti_fraud_as.main` | `5062/udp`, `8082/tcp` | Screens the caller; relays an **allowed** INVITE to AS-2, or answers `608 Rejected` itself |
| `as` (AS-2) | `python -m as_app.main` | `5060/udp`, `8080/tcp` | Receives the relayed INVITE, translates the number and routes to the core |
| `s-sbc-mock` | `python -m s_sbc_mock.main` | `15060/udp` UAC, `15061/udp` UAS | S-CSCF trigger on one side and the core on the other |

The wiring is configuration only: the mock's target and `FRAUD_SBC_PEER_*` point AS-1 at
AS-2, and AS-2's routing catalogue selects the core (ADR-0008 decision 1).

### 9.3 Interface view

The chain reuses the existing interfaces of section 3 and section 8.3. What is new is the
**trunk-to-trunk** interface between AS-1 and AS-2, and the two next-hop mechanisms behind it:

| Interface | Direction | Protocol | Notes |
| --- | --- | --- | --- |
| SIP trunk (allow) | S-SBC → AS-1 → AS-2 | SIP over UDP | AS-1 relays the **allowed** INVITE to its single configured next hop (`FRAUD_SBC_PEER_*` → `nh_addr`); no header added (ADR-0007) |
| Inter-AS next hop (translate) | AS-2 → core | SIP over UDP | AS-2 selects the next hop from its **routing catalogue** (`action.next_hops`), not from a peer knob (ADR-0008 decision 1) |
| Reject | S-SBC → AS-1 → S-SBC | SIP over UDP | `608 Rejected`, UAS-only, no second leg, so the call never reaches AS-2 (ADR-0007, REQ-F-027) |

**Every leg carries its own dialog `Call-ID`.** A chained call therefore shows **three**
distinct values instead of one: the S-CSCF leg's, the inter-AS leg's (AS-1's outbound leg,
derived by `outbound_call_id()` in `src/as_app/sip_adapter.py`) and the core leg's (AS-2's
outbound leg, derived from the value AS-2 received). `Call-ID` is not a pass-through header
— it crosses inside the call-control event, and **each controller derives it for the leg it
originates** (`docs/architecture/lld.md` section 2.3, ADR-0008 decision 2). Two consequences
follow, and both are stated rather than discovered:

- **Cross-AS correlation is not solved** on `Call-ID`, and cannot be: each instance writes
  its own trace and console feed keyed by the value *it* saw on its trunk leg, so a chained
  call is **three independent per-instance traces**, which is what `REQ-NF-016` registers as
  a POC gap. **The standard end-to-end key is nevertheless on the wire**: the
  `P-Charging-Vector`'s ICID is in `PASSTHROUGH_HEADERS` (section 3), both instances copy it
  verbatim, and the probe measures it surviving every hop — but **no observability surface is
  keyed on it**, and the mock's ICID is a per-scenario literal rather than a per-call
  identity. Re-keying the traces on the ICID is a change to both instances' observability
  contract and is P10's material, not P9's (ADR-0008 decision 4).
- **The demo makes the distinct values visible** by printing the `Call-ID` each hop saw,
  rather than presenting a correlation that does not exist (`REQ-F-028`, ADR-0008 decision 4).

### 9.4 Key message flows

**Allow path — through both B2BUAs.** AS-1 screens the caller, relays the unchanged INVITE to
AS-2; AS-2 translates and routes to the core.

```mermaid
sequenceDiagram
    participant UAC as mock UAC (S-CSCF)
    participant FRAUD as AS-1 anti-fraud
    participant AS as AS-2 number translation
    participant UAS as mock UAS (core)
    UAC->>FRAUD: INVITE (P-Asserted-Identity = caller)
    FRAUD->>FRAUD: screen(caller) -> allow
    FRAUD->>AS: INVITE (relayed, no header added)
    AS->>AS: translate +8613800138000 -> 013800138000 (R-MOB-CM-40)
    AS->>UAS: INVITE sip:013800138000@core
    UAS-->>AS: 100 Trying
    AS-->>FRAUD: 100 Trying
    FRAUD-->>UAC: 100 Trying
    UAS-->>AS: 180 Ringing
    AS-->>FRAUD: 180 Ringing
    FRAUD-->>UAC: 180 Ringing
    UAS-->>AS: 200 OK
    AS-->>FRAUD: 200 OK
    FRAUD-->>UAC: 200 OK
    UAC->>FRAUD: ACK
    FRAUD->>AS: ACK
    AS->>UAS: ACK
    UAC->>FRAUD: BYE
    FRAUD->>AS: BYE
    AS->>UAS: BYE
    UAS-->>AS: 200 OK
    AS-->>FRAUD: 200 OK
    FRAUD-->>UAC: 200 OK
```

**Reject path — short-circuits the chain.** AS-1 answers `608 Rejected` on the trunk and
originates no second leg, so **AS-2 and the core never receive the call**. The demo asserts
this as an absence — zero calls seen by AS-2, zero INVITEs at the core — not merely as the
status code (ADR-0008 decision 5).

```text
UAC (S-CSCF)              AS-1 anti-fraud            AS-2 number translation        core
    |                          |                              |                        |
    |--- INVITE -------------->|                              |                        |
    |                          | screen(caller) -> reject     |                        |
    |<-- 100 Trying -----------|                              |                        |
    |<-- 608 Rejected ---------|                              |                        |
    |--- ACK ----------------->|                              |                        |
    |                          |                              |                        |
    |              (no INVITE reaches AS-2 or the core; the chain ends here)           |
```

### 9.5 What the chain does not change

The chain is **demonstration, not architecture**: it adds no module, no shared library and no
interface between the two AS instances, and it is not the abstraction P10 has to build
(ADR-0008 decision 7). The friction it exposes — that AS-1 relays to a configured peer while
AS-2 routes by catalogue, and that **each self-written controller has to derive its own
outbound dialog identity** (a step that was omitted twice, in two copies of the same code) —
is P10's input and is recorded at the item's close (`docs/phase2-plan.md` section 3 P9,
section 5.4).

## 10. The platform library (P10)

`docs/phase2-plan.md` D8 splits the repository in two stages: stage one put the anti-fraud AS
**in this repository** (section 8), so the second use case could reuse the mock, the console,
the test scaffolding and the document set; stage two extracts the **skeleton shared by the two
AS instances** into a library in a new repository, after which this repository becomes the
library's **reference implementation and first user** (ADR-0009). This section adds the library
to the system context, the deployment view and the interface view. It extends the views above
rather than replacing them: the two AS instances, their console and their three demos are
unchanged (sections 8, 9).

### 10.1 System context

**The library is a build-time dependency, not a runtime component.** Nothing new is deployed:
the process topology of section 8.2 — the two AS instances, the two mocks and the console — is
unchanged, and the library adds **no process, no port and no listener**. It sits on the build
path only: `uv` resolves it when this repository's environment is created, and the extracted
code runs **inside** the two AS processes exactly where it ran before (ADR-0009 decisions 1
and 2).

```mermaid
graph LR
    subgraph lib["as_platform (sibling checkout)"]
        PLAT["library: the shared skeleton<br/>observability, sip_adapter, errors,<br/>bootstrap, controller/call-map/stack shells,<br/>transport + state-store seams"]
    end
    subgraph ours["this repository — the reference implementation"]
        AS["src/as_app/<br/>number translation"]
        FRAUD["src/anti_fraud_as/<br/>anti-fraud"]
    end
    PLAT -. "build-time import<br/>(no wire, no port)" .-> AS
    PLAT -. "build-time import<br/>(no wire, no port)" .-> FRAUD
    FRAUD -. "imports as_app's skeleton surface (ADR-0007 decision 9)" .-> AS
```

**This repository is the library's reference implementation (REQ-F-029): the library is
developed against two real consumers, not against an imagined one.** The two consumers are
`src/as_app/` (number translation, the Phase 1 AS) and `src/anti_fraud_as/` (anti-fraud, the
P8 AS). A library induced from one use case would be shaped like it; the extraction has exactly
two samples, which is both the reason the seams exist and the limit of what they prove
(ADR-0009, *Gaps accepted*).

### 10.2 Deployment view

**What changes on a machine is the checkout, not the topology.** The library repository
`as_platform` must be checked out **beside** this one (`../as_platform`), and `AGENT.md`
section 10's guarantee *"clone → `uv sync` → `make demo`"* becomes **"clone both repositories
side by side → `uv sync` → `make demo`"** (REQ-F-032, ADR-0009 decision 6). There is **no new
environment variable, no new port and no new service**: the library is not deployed, and the
port matrices of sections 8.2 and 9.2 are untouched.

| Checkout | Path | Role |
| --- | --- | --- |
| this repository | the working tree | the library's **reference implementation** and first user |
| `as_platform` | `../as_platform` (sibling) | the library; consumed through a `path` source |

The sibling layout is not a convention: the `path` in `pyproject.toml` is resolved **relative
to the consuming `pyproject.toml`**, so `../as_platform` means a sibling of this repository's
root and a deeper nesting does not find it (ADR-0009, *Verified facts* (f)). A checkout with
only this repository does not resolve `as-platform` at all (*Verified facts* (a)).

### 10.3 Interface view

The library's public surface is grouped below; each group's reasoning is in ADR-0009 and is not
re-argued here. Everything in the table is imported **by this repository**, and the library
imports neither application (REQ-F-030).

| Surface | What it is | ADR-0009 |
| --- | --- | --- |
| error mechanism | the memberless `ErrorCode`, `SIP_PHRASES`, `sip_status_for`, `AsError`, and the `SkeletonErrorCode` family | decision 3 |
| observability | structured logging, counters/dispositions/peer status, per-Call-ID trace and console feed | decision 2 |
| sippy adapter | `PASSTHROUGH_HEADERS`, `B2BUA_CALL_ID_SUFFIX`, `outbound_call_id`, `extract_called_number`, `is_allowed_peer`, `cancel_transaction_timers`, `CallLeg` | decision 2 |
| bootstrap plumbing | `ShutdownController`, `install_signal_handlers`, `check_port_available` | decision 2 |
| controller shell | `BaseCallController`, `BaseCallMap`, `PolicyDecision` | decision 4 |
| stack shell | `BaseAsStack` | decision 4 |
| internal-API shell | the app factory, `InternalApiServer` and the payload builders, generalised over a payload provider | decision 2 |
| transport seam | `Transport` / `UdpTransport` | decision 5 |
| state-store seam | `StateStore` / `InMemoryStateStore` | decision 5 |
| version | the distribution → `VERSION` chain | decision 2 |

**The direction rule the library must satisfy is one-way (REQ-F-030):** `as_platform` imports
**neither** `as_app` nor `anti_fraud_as`, so it carries the skeleton and not either use case.
The other direction is unchanged: `src/anti_fraud_as/**` continues to import `as_app`'s skeleton
surface as it does today (ADR-0007 decision 9), and the assertable invariant
`src/as_app/**` ↛ `anti_fraud_as` (REQ-F-026, REQ-F-030) still holds.

### 10.4 Key message flows

**No message flow changes, and that is the point.** The extraction moves where the skeleton's
code lives, not what any process does with a message: the relay, the failover walk, the `608`
reject, the per-leg `Call-ID` derivation and the ICID pass-through of sections 4, 8.4 and 9.4
are the same code in the same processes on the same wire. The heading is kept for structural
symmetry with sections 8 and 9; its content is the absence of a flow delta (REQ-F-031).

### 10.5 What the extraction does not change

- **The SIP signalling on the trunk is byte-identical.** The same messages, headers,
  Request-URI, SDP body and pass-through header set cross every leg (ADR-0009 decision 2).
- **The `AS-*` codes, SIP statuses and reason phrases are unchanged.** `SIP_PHRASES` —
  including `608: "Rejected"` — moves once, so the phrase cannot drift between families
  (ADR-0009 decision 3).
- **The per-instance Call-ID-keyed trace and console feed are unchanged.** Each AS still keys
  its trace, log and console feed on the `Call-ID` it saw on its trunk leg (sections 9.3, 9.4).
- **The two AS instances remain independent processes.** No process boundary moves, and the
  extraction adds no import between them (section 8.1).
- **`make demo` / `make demo-fraud` / `make demo-chained` still place real calls.** The three
  documented entry points keep working from a clean checkout, with the second checkout in place
  (REQ-F-032).
- **The three test layers stay green** — unit, integration and e2e (REQ-F-031, `AGENT.md`
  section 11). The one bounded exception is recorded in ADR-0009 decision 3 and changes no
  assertion.

**The extraction is a pure refactor with no wire-visible change.** It moves the skeleton both
AS instances already share into a library in a new repository; it changes where code lives, not
what the system does.

### 10.6 What it changes for a developer

- **Two repositories to clone.** A developer clones both checkouts side by side; a working tree
  with only this repository does not resolve the dependency (section 10.2).
- **A change to the library's API obliges this repository.** As the reference implementation,
  this repository follows the library in the same piece of work — it is the first user, not a
  consumer at a distance (ADR-0009, *Consequences*; D8).

