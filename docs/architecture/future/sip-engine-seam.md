# Future direction: SIP engine seam (stack-agnostic B2BUA)

**Status:** proposed — not scheduled; captures architecture discussion (2026-09-24)  
**Related:** ADR-0001 (sippy today) · ADR-0005 (mock on sippy) · ADR-0009 (platform extraction) ·
ADR-0010 (`Transport` seam) · LLD §11.2 (`PolicyDecision` / `decide()` hook) ·
`docs/production-gaps.md` (B2BUA shell row)

---

## 1. Question

If the AS replaces sippy with another SIP stack, can:

- mock / tests / tools **keep sippy** (UDP wire only), and
- the **app repository** (`as_app`, `anti_fraud_as`) stay **unchanged**,

by extracting a stack-neutral middle layer in **`as_platform`**?

**Short answer:** yes **after one migration**; not **zero work** today. The middle layer belongs in
`as_platform`; future stack swaps are platform-only **once apps stop constructing sippy types**.

---

## 2. Current stack ownership (today)

### 2.1 Who calls sippy?

| Layer | Module | sippy coupling |
| --- | --- | --- |
| **Platform** | `as_platform/main.py` (`BaseAsStack`) | `ED2.loop()`, `SipTransactionManager`, `SipConf`, `SipLogger` (~357 lines) |
| **Platform** | `as_platform/call_controller.py` (`BaseCallController`) | `UA`, `CCEvent*`, `Timeout`, request/response helpers (~1030 lines) |
| **App** | `as_app/call_controller.py`, `anti_fraud_as/call_controller.py` | **Minimal direct import** — `CCEventTry`, `CCEventFail`, `SipCallId`; `decide()` builds outbound events (~100 lines of sippy shape per app) |
| **App** | `as_app/route_header.py` | reads sippy request API (`getHFBodys("route")`) |
| **App** | `main.py` (both AS) | **No sippy import** — inherits `BaseAsStack` only |
| **Mock / tools** | `s_sbc_mock/`, `ims_mock/`, `tools/` | full sippy UAC/UAS |
| **Tests** | `tests/conftest.py` (integration) | drives AS via `ED2.loop()` in-process |
| **Console** | `src/console/` | **none** (HTTP/WS only) |

### 2.2 Call path (simplified)

```text
sippy SipTransactionManager
    → TrunkCallMap.recv_request()           [app: thin map]
    → BaseCallController.recv_request()     [platform: creates UA, uaA.recvRequest]
    → sippy CCEventTry
    → BaseCallController.recv_event()       [platform: relay shell]
    → apply_call_policy() → decide()        [app: routing / screening ONLY]
    → platform continues relay / reject / failover / timers
```

**The app does not drive the B2BUA.** It hooks **`decide()`** and today **hands back a sippy
`CCEventTry`** inside `PolicyDecision`.

### 2.3 What “~1400 lines B2BUA shell” means

Not “app calls sippy directly for everything”. It means **platform code already implements the
full relay state machine** on top of sippy:

- `recv_request` → terminate trunk INVITE, create answering `UA`
- `recv_event` → bidirectional relay trunk ↔ next-hop leg
- `_originate_towards` → originate outbound INVITE
- `_reject_on_trunk` → answer 4xx/6xx on trunk leg
- failover walk, no-answer timer, `CCEventConnect` / `Ring` / `Disconnect`, …

That shell is **implemented with sippy types today**. Replacing the stack means **rewriting or
adapting this shell**, not the routing/screening algorithms in app `decide()`.

---

## 3. Scenarios

### 3.1 Only AS stack changes; mock stays sippy (UDP)

**Wire-level:** feasible — both sides speak RFC 3261 SIP over UDP.

**In-process integration tests (`trunk_pair` + `ED2.loop()`):** the test harness drives the
**AS process event loop**. If the AS no longer uses `ED2`, integration tests need a **new drive
mechanism** (UDP black-box against sippy mock, or new stack test API). Mock code can stay sippy;
**how we test the AS** may change.

### 3.2 App repo “无感知”?

| Moment | App repo changes? |
| --- | --- |
| **First** introduction of engine seam | **Yes — once.** Remove `CCEventTry` / `SipCallId` construction; stop calling sippy request parsers; return pure-data `PolicyDecision`. |
| **Each later** stack swap in `as_platform` | **No** — if seam contract is stable. |

Console, rules engine, screening logic, internal API payloads: **already stack-agnostic**.

---

## 4. Proposed target architecture

Middle layer lives in **`as_platform`** (REQ-F-030: platform never imports app).

```text
┌─────────────────────────────────────────┐
│  this repo: as_app / anti_fraud_as       │
│  decide() → PolicyDecision (pure data)   │
└──────────────────┬──────────────────────┘
                   │ stable engine API
┌──────────────────▼──────────────────────┐
│  as_platform                             │
│  ┌────────────────────────────────────┐  │
│  │ B2buaEngine (stack-neutral)        │  │  relay, failover, timers, trace hooks
│  │  - InboundInvite                   │  │
│  │  - CallLegEvent                    │  │
│  │  - OutboundInviteSpec              │  │
│  └───────────────┬────────────────────┘  │
│                  │ adapter interface      │
│     ┌────────────┴─────────────┐         │
│  SippyAdapter              NewStackAdapter │
└─────────────────────────────────────────┘
```

### 4.1 Extend what already exists

P10 already extracted half the seam (ADR-0009 decision 4):

| Already stack-neutral | Still sippy-shaped |
| --- | --- |
| `PolicyDecision.action`, reject fields, `next_hops`, trace/log vocabulary | `PolicyDecision.outbound_event: CCEventTry` |
| `decide()` as the only app hook | `event.getData()`, `isinstance(CCEventFail, …)` in app |
| `Transport` seam (ADR-0010) | `BaseAsStack` + `SignallingLoop` = `ED2.loop()` |
| `outbound_call_id()` helper | `SipCallId(...)`, `route_header.getHFBodys()` |

**Main gap:** `outbound_event` and inbound event/request types must become **engine datatypes**,
not sippy classes.

### 4.2 Suggested engine types (illustrative)

```python
@dataclass(frozen=True)
class OutboundInviteSpec:
    trunk_call_id: str
    outbound_call_id: str
    calling_party: str
    called_party: str
    body: bytes | None
    max_forwards: int | None
    extra_headers: tuple[HeaderField, ...]  # or platform copies from trunk automatically

@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    outbound: OutboundInviteSpec | None  # replaces outbound_event: CCEventTry
    next_hops: list[NextHop]
    # ... reject fields unchanged ...
```

Platform adapter (`SippyAdapter`) converts `OutboundInviteSpec` → `CCEventTry` internally.

### 4.3 App migration (one time)

Per application controller (~100–150 lines touched each):

- Remove `from sippy.CCEvents import …` and `SipCallId`
- Replace `CCEventTry(...)` with `OutboundInviteSpec(...)` or `PolicyDecision.relay(...)`
- Move `parse_top_route_target(request)` usage to platform-provided fields on `InboundInvite`
- Keep all routing / screening / metrics / P12 logic unchanged

`as_app/route_header.py`: move into platform or replace with parsed fields on inbound context.

---

## 5. Work sizing (order-of-magnitude)

| Phase | Where | Effort | Outcome |
| --- | --- | --- | --- |
| **A — App decouple** | platform facade + app controllers | **2–4 person-days** | Apps have **zero** sippy imports; platform still runs sippy via adapter |
| **B — Engine extract** | refactor `BaseCallController` → `B2buaEngine` + `SippyAdapter` | **1–2 weeks** | Clean seam; behaviour parity via existing tests |
| **C — New stack adapter** | `NewStackAdapter` + `BaseAsStack` binding | **2–4+ weeks** | Depends on target stack B2BUA maturity |
| **D — Test harness** | integration: UDP black-box or dual loop driver | **3–5 person-days** | Mock stays sippy; AS tests no longer require `ED2.loop()` |

Phases A→B can ship **without** choosing a new stack. Phase C is the actual swap.

---

## 6. Non-goals

- Replacing sippy in **mock** (`s_sbc_mock`, `ims_mock`) — out of scope unless wire tests are
  insufficient.
- Changing **console** or **load generator** for stack work.
- Promising **byte-identical** SIP on the wire after stack swap — only RFC-correct behaviour
  (regression via existing message samples + integration tests).
- Solving **cross-stack in-process** tests where one process runs two stacks — prefer UDP
  black-box for AS-under-test.

---

## 7. Decision status

| Item | Status |
| --- | --- |
| Keep sippy for POC / v1.x | **Current** (ADR-0001) |
| Extract `B2buaEngine` seam in `as_platform` | **Proposed** — this document |
| Target replacement stack | **Not chosen** |
| ADR number | Reserve **ADR-0017** when implementation is scheduled |

When scheduled, deliver in order: **design note → ADR-0017 (accepted) → platform PR → app
one-time migration → test harness update → optional new adapter**.

---

## 8. References (code)

| Topic | Location |
| --- | --- |
| Platform B2BUA shell | `../as_platform/src/as_platform/call_controller.py` |
| Platform process shell | `../as_platform/src/as_platform/main.py` |
| App `decide()` + `CCEventTry` | `src/as_app/call_controller.py`, `src/anti_fraud_as/call_controller.py` |
| Route header on sippy request | `src/as_app/route_header.py` |
| Controller seam doc | `docs/architecture/lld.md` §11.2 |
| Transport seam (precedent) | ADR-0010, `as_platform.transport` |
