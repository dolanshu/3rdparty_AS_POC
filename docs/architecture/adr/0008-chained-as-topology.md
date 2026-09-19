# ADR-0008: Chained AS topology — configuration-only chaining and Call-ID preservation across two B2BUAs

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** project maintainer
- **Related:** `docs/phase2-plan.md` section 2 (D6) and section 3 (P9), section 5.1, section 6
  ("Port collision", "Chained Call-IDs") · `docs/requirements/functional-and-nonfunctional.md`
  (REQ-F-025…REQ-F-028, REQ-NF-016…REQ-NF-018) · ADR-0001 (sippy) · ADR-0002 (process
  separation) · ADR-0007 (anti-fraud AS) · `docs/architecture/hld.md` section 9 ·
  `docs/architecture/lld.md` section 2.3 and section 10 · `tools/chained_as_probe.py`

> **Pending rework — this ADR was written against a defective behaviour (maintainer ruling,
> 2026-09-19).** Decisions **2**, **3** and **4** below describe the **current** behaviour of
> the code as the probe measured it: the AS **reuses the inbound `Call-ID` on its outbound
> leg**, so one `Call-ID` spans the whole chain. The maintainer has ruled that a **Phase 1
> defect** — the code contradicts the design intent stated in
> `docs/architecture/lld.md` section 2.3 (`Call-ID` belongs to the dialog and the second leg
> has its own) — not accepted behaviour. **Decision 3 does not stand:** the premise it retires
> is the *intended* behaviour, so `REQ-NF-016` / `REQ-F-028` and the plan's section 6 and
> section 3 P9 keep their wording, and the rewording this ADR assigned to the implementation
> commit is **withdrawn**. The fix lands on **`main`** and is merged back into `phase2`;
> **P9 is paused** until then, and this ADR is to be **reworked when P9's design stage is
> redone** (`docs/phase2-plan.md` section 3, P9). The probe's measurements are true
> observations of the code as it stands and are kept.

## Context

P9 puts the two AS instances that already exist — the anti-fraud AS of P8 and the
number-translation AS of Phase 1 — **in series**, as
`SBC → AS-1 (anti-fraud) → AS-2 (number translation) → core`. `docs/phase2-plan.md` D6
places this before the platform work precisely because the friction between two real
instances is what P10 has to turn into an interface (ADR-0007 decision 9).

Three questions had to be settled before any demo exists:

1. **How is the chain wired?** D6 states *configuration only*, with no iFC emulation added
   to the mock. That is a claim about which knob decides the next hop, and the two instances
   do **not** read that knob the same way — so the wiring has to be named exactly, not
   described as "point one at the other".
2. **What does a reject do to the chain?** The anti-fraud AS rejects with `608` from the UAS
   side and originates no second leg (ADR-0007). The design has to state that a reject
   short-circuits the chain, and it must be observable rather than argued.
3. **What is the `Call-ID` of a chained call?** `docs/phase2-plan.md` section 6 and
   `REQ-NF-016` assert that *"two B2BUAs in series produce two different Call-IDs"*, that a
   B2BUA regenerates the dialog `Call-ID` for its second leg, and that cross-AS correlation
   is therefore **unsolved**. That premise is load-bearing — it decides whether P9 registers
   a gap or demonstrates a correlation — so it had to be measured rather than repeated.

## Decision

### 1. Chaining is configuration only, and the two hops are configured differently

The chain is wired from the existing knobs and the routing catalogue. **No code is changed,
no iFC emulation is added to the mock, and neither AS imports the other** (REQ-F-026).

| Hop | Decided by | Value for the chain |
| --- | --- | --- |
| S-CSCF → AS-1 | the mock's `--as-address` / `--as-port` (`MockConfig.as_address` / `as_port`) | AS-1's listen address |
| AS-1 → AS-2 | `FRAUD_SBC_PEER_ADDRESS` / `FRAUD_SBC_PEER_PORT` → `nh_addr` → `uaO.nh_address` | AS-2's SIP listen address |
| AS-2 → core | the **routing catalogue** (`action.next_hops` resolved against the file's `next_hops`) — **not** `SBC_PEER_*` | the emulated core |

The asymmetry is the point of the table: the anti-fraud AS relays an allowed INVITE to its
**single configured next hop**, so pointing `FRAUD_SBC_PEER_*` at AS-2 is the whole wiring;
the number-translation AS instead selects its next hop from the **rule set**, so the chain's
tail is a catalogue entry, not a peer setting. A demo that runs on dynamic ports must
therefore rewrite the catalogue's next-hop ports (the committed
`capture_call.rewrite_next_hop_ports` does exactly this) rather than only set environment
variables.

### 2. The dialog `Call-ID` is preserved across both B2BUAs

Measured, not assumed: a chained call carries **one** `Call-ID` from the S-CSCF to the core,
through both AS instances (`distinct Call-IDs: 1`). The mechanism is a stack behaviour plus a
decision both controllers already make, and neither is the "regenerate per leg" the plan
assumed:

1. `UasStateIdle.recvEvent` takes the trunk `Call-ID` off the received request
   (`self.ua.cId = self.ua.uasResp.getHFBody('call-id')`) and puts it into the call-control
   event as element `[0]`: `CCEventTry((self.ua.cId, …))`.
2. Both controllers **rebuild** that event and keep element `[0]`: `as_app` builds
   `CCEventTry((original[0], original[1], translated, …))` and `anti_fraud_as` builds
   `CCEventTry(event.getData())`.
3. `UacStateIdle.recvEvent` **reuses** a `Call-ID` it is handed instead of generating one:
   `if cId == None: self.ua.cId = SipCallId() else: self.ua.cId = cId.getCopy()`.

`Call-ID` is **absent** from `PASSTHROUGH_HEADERS`, but it does not cross as a copied header —
it crosses inside the call-control event, which is why the pass-through set does not decide
this question. The two facts are not in conflict; reading only the header table is what makes
the plan's premise look true.

### 3. The "two B2BUAs produce two Call-IDs" premise is wrong, and is retired

The premise is stated in four places and is **factually wrong for this codebase**: the plan's
section 6 ("Chained Call-IDs"), the plan's section 3 P9 ("Known issue"), `REQ-NF-016` and
`REQ-F-028`. Correcting requirement and plan text is not this stage's job; the correction is
assigned to the item's **implementation commit** (`docs/architecture/lld.md` section 10.5),
which must reword those four places to the measured behaviour without changing the intent of
`REQ-F-028` (per-instance observability remains true: each instance still writes its own
Call-ID keyed trace and console feed).

### 4. Cross-AS correlation is solved by construction, not registered as a gap

Because the `Call-ID` is preserved, a chained call is a **single correlated trace across both
instances**: the Call-ID the S-CSCF used, the Call-ID AS-2 saw on its trunk leg and the
Call-ID the core saw are the same string. P9 therefore demonstrates correlation rather than
registering its absence. The demo makes that visible — it prints the `Call-ID` each hop saw —
so a reviewer sees the property instead of a claim.

**The reliance is stated, not hidden.** This behaviour is a property of the pinned sippy
version and of both controllers keeping event element `[0]`; it is **relied upon but not
mandated** by anything in the design. A production deployment must not depend on it:
`P-Charging-Vector` (the ICID, which ties both legs to one charging record) **is** in
`PASSTHROUGH_HEADERS` and is the standard, end-to-end correlation key. That is recorded below.

### 5. A reject short-circuits the chain

A `608` reject at AS-1 is answered on the trunk and originates no second leg (ADR-0007), so
AS-2 and the core never receive the call. The probe asserts it as an **absence** — zero calls
seen by AS-2, zero INVITEs at the core — not merely as a `608` on the wire, because "the call
never arrived" is the property the chain depends on.

### 6. `make demo-chained`, and no new knob

P9 introduces one **first-class, documented run command**, mirroring `make demo` /
`make demo-fraud` (REQ-NF-017):

```bash
make demo-chained     # -> uv run python tools/demo_chained_call.py
```

It runs the chained topology on dynamically allocated ports, writes nothing, and needs **no
new environment variable and no new port** — the two AS listen ports (`5060` / `5062`)
already differ precisely so both instances can run on one host (plan section 6). A changed run
command is a **structural change** (`AGENT.md` section 13), so the implementation commit must
update `AGENT.md` section 10, `README.md` and `docs/README.md` in the same commit; that
obligation is stated in `docs/architecture/lld.md` section 10.5.

### 7. The chain is P10's input, not the abstraction

Nothing here is designed for reuse by a third use case. The friction the chain exposes — that
the two instances configure their next hop in two different ways, that the routing catalogue
couples a dial plan to a peer inventory, and that the correlation key is a stack behaviour
rather than a declared contract — is exactly the material P10 must turn into an interface
(`docs/phase2-plan.md` D2, ADR-0007 decision 9).

## Verified facts (measured on this machine, 2026-09-19)

sippy behaviour is observed, never assumed (`AGENT.md` section 6). The probe is committed as
**`tools/chained_as_probe.py`** and is a design instrument, in the precedent of
`tools/anti_fraud_probe.py`. It runs the real stacks in one interpreter, on dynamically
allocated ports, and **asserts** the three properties — it exits non-zero on any mismatch, so
it is a guard rather than a printout. It is not collected by pytest and does not run in CI.

Command:

```bash
uv run python tools/chained_as_probe.py
```

Observed output (ports and Call-IDs are ephemeral and vary per run; the rest is verbatim,
exit code `0`):

```text
chained AS POC - two B2BUAs in series, wired by configuration only
topology   : emulated S-CSCF --UDP--> AS-1 anti-fraud --UDP--> AS-2 number translation --UDP--> emulated core
ports      : AS-1 127.0.0.1:45229, AS-2 127.0.0.1:46793, trunk 47944, core 47053
wiring     : AS-1 next hop = AS-2 listen address; AS-2 next hop = the rule set

[1/2] allowed call relayed through both AS instances
caller        : +86216180001
called        : +8613800138000
AS-1 verdict  : allow
AS-1 signal   : none
S-CSCF Call-ID: 4e45be8db92330434c319642120149de
AS-2 trunk Call-ID: 4e45be8db92330434c319642120149de
AS-2 rule     : R-MOB-CM-40
core Call-ID  : 4e45be8db92330434c319642120149de
core called number: 013800138000
final status  : 200
released      : True
distinct Call-IDs: 1
Call-ID preserved: True

[2/2] rejected call short-circuits at AS-1
caller        : +8613400000001
AS-1 verdict  : reject
final status  : 608
AS-2 calls seen: 0
core INVITEs seen: 0

--- verdict --------------------------------------------------------
allowed call completed through two B2BUAs : OK
608 reject short-circuited before AS-2     : OK
Call-ID preserved across both B2BUAs       : OK
```

**Conclusion.** All three design assumptions hold: an allowed call completes through both
B2BUAs (`200`, released, the core saw the translated number `013800138000` under rule
`R-MOB-CM-40`), a `608` reject never reaches AS-2 or the core, and **one `Call-ID` spans the
whole chain**. The mechanism behind the third is quoted in Decision 2 from
`sippy/UasStateIdle.py`, `sippy/UacStateIdle.py`, `src/as_app/call_controller.py` and
`src/anti_fraud_as/call_controller.py`.

**What the probe does not prove.** It runs the two stacks in **one interpreter**, as
`tools/demo_call.py` and `tools/demo_fraud_call.py` do, because that is how the repository's
tools drive sippy. It therefore exercises the two instances' *logic and wiring*, not the
process boundary of a real deployment; `SipConf` and `ED2` are process-wide singletons
(section 5 of the LLD), so the production shape is **three processes**. The probe's own
comment records that each stack is given its own `TraceRecorder` / `MetricsRegistry` because
those default to process-wide singletons — a single shared recorder would mix the two
instances' traces and hide the very thing being measured.

## Consequences

- **P9 needs no code change to chain.** The wiring is `FRAUD_SBC_PEER_*` on one side and a
  catalogue entry on the other, so the demo is a run command plus documentation, not an
  implementation of chaining.
- **A chained call is one correlated trace, not two.** The correlation `REQ-NF-016` treated as
  unsolved is present by construction, so the demo asserts it and the requirement's premise
  is corrected in the implementation commit (Decision 3).
- **A reject is observable as an absence.** The chain's short-circuit property is asserted by
  what AS-2 and the core did *not* receive, which is stronger evidence than a status code.
- **The chain exposes the two next-hop mechanisms.** That AS-1 relays to a configured peer
  while AS-2 routes by catalogue is the concrete friction P10 inherits, and it is why the demo
  has to rewrite catalogue ports.
- **`make demo-chained` is a structural change.** It obliges `AGENT.md` section 10,
  `README.md` and `docs/README.md` to be updated in the implementation commit
  (`AGENT.md` section 13).
- **The correlation key is a stack behaviour, not a contract.** Any future change to how a
  controller rebuilds `CCEventTry`, or a sippy upgrade that changes `UacStateIdle`, can break
  Call-ID preservation silently. The probe is the guard that turns that into a failure.

## Gaps accepted

Each of the following is destined for `docs/production-gaps.md` in the **implementation
commit** — stated here, not registered now, because the register records behaviour that
exists.

- **No iFC / ISC emulation.** The mock drives the chain as a direct trunk call; a real
  deployment triggers each AS from the S-CSCF by iFC and applies Initial Filter Criteria to
  route one AS's output into the next. Production: model the S-CSCF trigger and the iFC that
  inserts a second AS in the chain.
- **Call-ID preservation is relied upon but not mandated.** It is a property of the pinned
  sippy version plus both controllers keeping event element `[0]` (Decision 2), and nothing
  in the design declares it a contract. Production: correlate on the standard end-to-end key —
  `P-Charging-Vector`'s ICID, which **is** in `PASSTHROUGH_HEADERS` — rather than on `Call-ID`.
- **No shared state between the two instances.** AS-1's screening state and AS-2's rule set are
  independent and neither sees the other's decision; the chain has no shared call context.
  Production: a shared session/charging context if the chain has to make a joint decision.
- **The routing catalogue couples the dial plan to the peer inventory.** AS-2's next hop is a
  catalogue entry, so the chain's tail cannot be changed without editing (or rewriting) the
  rule file; this is the rule-file-drift trap of plan section 6 seen from a second angle.
- **No ordering, capacity or failure semantics for the chain.** P9 demonstrates the topology;
  what happens when AS-2 is down, or how the two instances' capacities compose, is P9.5's
  discovery input and is not answered here.
- **The probe runs both instances in one interpreter.** The real deployment is three
  processes; the probe exercises the wiring and the logic, not the process boundary
  (*Verified facts*, "What the probe does not prove").
