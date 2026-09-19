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
before the platform work precisely to expose the friction between the two instances.

### 8.2 Deployment view

Four processes now. The anti-fraud AS is a separate process for the same reason as the
number-translation AS (ADR-0002): sippy's `ED2.loop()` blocks, so its internal API runs in
its own process and on its own port, and the two AS instances must not share a listen port
(D6, and the port-collision trap in `docs/phase2-plan.md` section 6).

```mermaid
graph TB
    subgraph host["docker compose host"]
        AS["as<br/>UDP 5060 (trunk)<br/>TCP 8080 (internal API)"]
        FRAUD["anti-fraud-as<br/>UDP 5062 (trunk)<br/>TCP 8082 (internal API)"]
        MOCK["s-sbc-mock<br/>UDP 15060 (UAC)<br/>UDP 15061 (UAS)"]
        CONSOLE["console<br/>TCP 8081"]
    end
    MOCK == "INVITE" ==> AS
    MOCK == "INVITE" ==> FRAUD
    AS == "translated INVITE" ==> MOCK
    FRAUD == "relayed INVITE (allow)" ==> MOCK
    CONSOLE -- "HTTP / WS" --> AS
    CONSOLE -- "HTTP / WS" --> FRAUD
```

| Service | Process | Ports | Purpose |
| --- | --- | --- | --- |
| `as` | `python -m as_app.main` | `5060/udp` trunk, `8080/tcp` internal API | Number translation and routing (Phase 1) |
| `anti-fraud-as` | `python -m anti_fraud_as.main` | `5062/udp` trunk, `8082/tcp` internal API | Caller screening: allow or `608 Rejected` (P8) |
| `s-sbc-mock` | `python -m s_sbc_mock.main` | `15060/udp` UAC side, `15061/udp` UAS side | Emulates the S-CSCF trigger and the core network |
| `console` | `python -m console.main` | `8081/tcp` | Operations UI, reaches each AS over its internal API |

Every port is configuration and **no default silently points at a real network**; the port
matrix in `docs/operations/deployment.md` is extended with the second AS in the
implementation commit. The distinct listen port (`5062`) is a deliberate default: without
it, running both instances locally collides on `5060`, which is the trap recorded in
`docs/phase2-plan.md` section 6.

### 8.3 Interface view

| Interface | Direction | Protocol | Notes |
| --- | --- | --- | --- |
| SIP trunk (reject) | S-SBC → anti-fraud AS → S-SBC | SIP over UDP | The AS terminates the INVITE and answers it **from the UAS side only**: `608 Rejected`, no second leg, no `Call-Info` (ADR-0007) |
| SIP trunk (allow) | S-SBC → anti-fraud AS → S-SBC | SIP over UDP | The AS relays the INVITE **unchanged** as a B2BUA (Request-URI and headers untouched, **no added header**) and relays the response back |
| Calling identity | inside the INVITE | `P-Asserted-Identity` | The screening input: the AS inspects the *calling* party, not the called number (D4) |
| Internal API | console → anti-fraud AS | HTTP (REST) + WebSocket | `GET /healthz`, `/api/v1/metrics`, `/api/v1/screening`, `/api/v1/traces`, `WS /ws/events` |
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

