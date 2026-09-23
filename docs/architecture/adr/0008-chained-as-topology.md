# ADR-0008: Chained AS topology — configuration-only chaining and a distinct Call-ID per B2BUA leg

- **Status:** Accepted (decision 1 **superseded** by ADR-0014 — kept as historical evidence)
- **Date:** 2026-09-19
- **Deciders:** project maintainer
- **Related:** `docs/phase2-plan.md` section 2 (D6) and section 3 (P9), section 5.1, section 6
  ("Port collision", "Chained Call-IDs") · `docs/requirements/functional-and-nonfunctional.md`
  (REQ-F-025…REQ-F-028, REQ-NF-016…REQ-NF-018) · ADR-0001 (sippy) · ADR-0002 (process
  separation) · ADR-0007 (anti-fraud AS) · `docs/architecture/hld.md` section 9 ·
  `docs/architecture/lld.md` section 2.3 and section 10 · `tools/chained_as_probe.py`

> **Reworked 2026-09-19 (P9 stage 2, second pass).** The first pass was written against a
> defective behaviour: the AS reused the inbound `Call-ID` on its outbound leg, so the probe
> measured **one** `Call-ID` across the whole chain (`distinct Call-IDs: 1`), and decisions 2,
> 3 and 4 below were written to that observation. The maintainer ruled the reuse a **Phase 1
> defect** — the code contradicted the design intent of `docs/architecture/lld.md` section 2.3
> — had it fixed on **`main`** (`f1b4186`, merged back into `phase2` as `76a95da`) and
> **paused P9** until that landed. P9 then resumed and this stage was redone on the fixed
> behaviour (`docs/phase2-plan.md` section 3, P9). Decisions 2 and 4 and the measurements
> below are rewritten; the withdrawn decision 3 is folded into decision 3 as it now stands.
> The first pass's *observations* are kept where they are history, and marked as such.

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
   a gap or demonstrates a correlation — so it had to be measured rather than repeated. It
   also turned out to be a **defect report against the code**, not merely a design question:
   the first probe measured the opposite of the premise, which is how the Phase 1 defect was
   found.

## Decision

### 1. Chaining is configuration only, and the two hops are configured differently

The chain is wired from the existing knobs and the routing catalogue. **No code is changed
to make chaining work, no iFC emulation is added to the mock, and neither AS imports the
other** (REQ-F-026).

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

### 2. Every B2BUA gives its outbound leg its own `Call-ID`

**A chained call carries three distinct `Call-ID` values, one per leg**, because each B2BUA
regenerates the dialog identity of the leg it originates. With the S-CSCF leg's value
written `X`:

| Leg | `Call-ID` | Produced by |
| --- | --- | --- |
| S-CSCF → AS-1 trunk | `X` | the mock UAC |
| AS-1 → AS-2 (inter-AS) | `X-b2b_1` | AS-1's outbound leg |
| AS-2 → core | `X-b2b_1-b2b_1` | AS-2's outbound leg |

The mechanism is a single source of truth plus a stack behaviour that has to be worked
around:

1. `UasStateIdle.recvEvent` takes the trunk `Call-ID` off the received request
   (`self.ua.cId = self.ua.uasResp.getHFBody('call-id')`) and puts it into the call-control
   event as element `[0]`: `CCEventTry((self.ua.cId, …))`.
2. `UacStateIdle.recvEvent` would **reuse** a `Call-ID` it is handed instead of generating
   one (`if cId == None: self.ua.cId = SipCallId() else: self.ua.cId = cId.getCopy()`), and
   only sippy's own `CCB2BUA` rewrites it for the second leg (`sippy/b2bua.py`, the `-b2b_N`
   suffix by default). This project runs its **own controller over a bare `sippy.UA`**, so
   nothing rewrites it unless the controller does.
3. Both controllers therefore build the outbound `CCEventTry` with a **fresh** `SipCallId`:
   `outbound_call_id()` in `src/as_app/sip_adapter.py` appends sippy's own suffix
   (`B2BUA_CALL_ID_SUFFIX = "-b2b_1"`) to the trunk value, and the inbound `SipCallId` object
   is never mutated. Route `1` is the AS's single outbound leg, and every failover hop
   reuses the same value because the translated event is built once and stored in
   `_pending_event`, so one call has exactly one outbound `Call-ID`.

`Call-ID` is **absent** from `PASSTHROUGH_HEADERS`, and that is now incidental: it does not
cross as a copied header but inside the call-control event, where each controller rebuilds
it. Reading only the header table is what made the defect invisible.

**Both instances, not one.** The Phase 1 fix landed this for the number-translation
instance (`src/as_app/call_controller.py`). `src/anti_fraud_as/call_controller.py` had its
**own copy of the same defect** — it builds `CCEventTry(event.getData())`, keeping element
`[0]` — and the file exists only on `phase2`, so the Phase 1 fix could not reach it
(`docs/phase2-plan.md` section 3 P9, finding (A)). It is fixed in **P9's implementation
stage**, which is also what turns the reworked probe green.

### 3. The "two B2BUAs produce two Call-IDs" premise stands, and the code is made to match it

The premise is stated in the plan's section 6 ("Chained Call-IDs"), the plan's section 3 P9
("Known issue"), `REQ-NF-016` and `REQ-F-028`. The maintainer's ruling of 2026-09-19 is that
it describes the **intended** behaviour and that the code, not the text, was wrong: the
requirement wording is **not changed**, and the first pass's decision 3 — which retired the
premise as "factually wrong" and assigned a rewording of those four places to P9's
implementation commit — is **withdrawn**. The `lld.md` section 10.5 rows that carried that
assignment are withdrawn with it.

`REQ-F-028` remains true for a second reason: each instance still writes its **own**
`Call-ID` keyed trace and console feed, keyed by the `Call-ID` **it** saw on its trunk leg,
so a chained call is observable per instance even though the values now differ.

### 4. Cross-AS correlation on `Call-ID` is not solved; the ICID is on the wire but nothing uses it

Because every leg regenerates the identity, **the `Call-ID` cannot be used to correlate
across the two AS instances**: the value the S-CSCF used, the value AS-2 saw on its trunk
leg and the value the core saw are three different strings. P9 therefore **registers the
absence** rather than demonstrating a correlation on `Call-ID`, exactly as `REQ-NF-016`
states.

**The standard alternative key is present and is preserved — measured, not assumed.** The
correlation key a production deployment uses is the `P-Charging-Vector`'s **ICID** (3GPP
TS 24.229), which ties both legs to one charging record. The probe now reads it at each hop
and it survives the whole chain:

```text
S-CSCF ICID   : poc-chained-allow
AS-2 ICID     : poc-chained-allow
core ICID     : poc-chained-allow
ICID preserved: True
```

That is expected rather than surprising: `p-charging-vector` **is** in `PASSTHROUGH_HEADERS`,
so both controllers copy it verbatim, and it is the pass-through set — not the `Call-ID` —
that decides this. **The first pass of this ADR claimed the mock emitted no
`P-Charging-Vector` at all and that the POC therefore had no end-to-end key; that was
wrong**, and it was wrong because it was reasoned from the design instead of measured. The
mock has always emitted one (`MockUac._isc_headers`).

**So the gap is narrower and more precise than "no key exists".** Two things are still true,
and they are what the register records:

1. **The mock's ICID is a per-scenario literal, not a per-call identity.**
   `MockUac._isc_headers` writes `icid-value=poc-{scenario.name}`, so two calls placed from
   the same scenario carry the **same** ICID. It therefore proves pass-through but does not
   identify a call, and it could not be used to correlate real traffic.
2. **Nothing in the AS consumes it.** Each instance keys its trace, its structured log, its
   metrics and its console feed on the `Call-ID` **it** saw on its trunk leg
   (`AGENT.md` section 4.3, `REQ-NF-005`). The end-to-end key is on the wire but no
   observability surface is keyed on it, so an operator wanting to follow one call across two
   instances has to join the two feeds out of band. Correlating the **traces** is what is
   unsolved, which is the sense in which `REQ-NF-016` is true.

Demonstrating a working cross-AS correlation would mean re-keying both instances' trace and
console feeds on the ICID, or emitting an explicit correlation record. That is a change to
the observability contract of both AS instances — a platform concern, and therefore P10's
material, not P9's. `AGENT.md` section 12 forbids building it here because P9 has no second
requirement for it.

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
couples a dial plan to a peer inventory, and that **each instance has to remember to
regenerate the dialog identity itself** — is exactly the material P10 must turn into an
interface (`docs/phase2-plan.md` D2, ADR-0007 decision 9). The third item is new since the
first pass: the defect was a *shared* mistake made twice, which is a stronger argument for
extraction than any of the others.

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

**Observation on the first pass — the defective code (the Phase 1 defect).** Recorded as
history; it is what the pause was called on. A **single** `Call-ID` spanned the chain, the
first pass's assertion "Call-ID preserved" passed, and the premise of `REQ-NF-016` looked
wrong:

```text
S-CSCF Call-ID: 4e45be8db92330434c319642120149de
AS-2 trunk Call-ID: 4e45be8db92330434c319642120149de
core Call-ID  : 4e45be8db92330434c319642120149de
distinct Call-IDs: 1
Call-ID preserved: True
```

**Observation on the reworked probe — after the Phase 1 fix, before P9's implementation
stage.** The reworked probe asserts the *intended* per-leg property instead, and reports
**three** distinct values as the target. It measured two, because AS-1 still carries its own
copy of the defect (decision 2, finding (A)) — so the probe is **red until P9 stage 3 fixes
the anti-fraud controller**, which is precisely what a design-stage guard is for. It also
reads the ICID at each hop, which is what corrected decision 4. Ports and `Call-ID`s are
ephemeral and vary per run; the rest is verbatim:

```text
chained AS POC - two B2BUAs in series, wired by configuration only
topology   : emulated S-CSCF --UDP--> AS-1 anti-fraud --UDP--> AS-2 number translation --UDP--> emulated core
ports      : AS-1 127.0.0.1:48527, AS-2 127.0.0.1:45239, trunk 47361, core 47327
wiring     : AS-1 next hop = AS-2 listen address; AS-2 next hop = the rule set

[1/2] allowed call relayed through both AS instances
caller        : +86216180001
called        : +8613800138000
AS-1 verdict  : allow
AS-1 signal   : none
S-CSCF Call-ID: 3030128278b9cedf429594ad44fe7e28
AS-2 trunk Call-ID: 3030128278b9cedf429594ad44fe7e28
AS-2 rule     : R-MOB-CM-40
core Call-ID  : 3030128278b9cedf429594ad44fe7e28-b2b_1
core called number: 013800138000
final status  : 200
released      : True
distinct Call-IDs: 2
Call-ID per leg: False
S-CSCF ICID   : poc-chained-allow
AS-2 ICID     : poc-chained-allow
core ICID     : poc-chained-allow
ICID preserved: True

[2/2] rejected call short-circuits at AS-1
caller        : +8613400000001
AS-1 verdict  : reject
final status  : 608
AS-2 calls seen: 0
core INVITEs seen: 0

--- verdict --------------------------------------------------------
allowed call completed through two B2BUAs : OK
608 reject short-circuited before AS-2     : OK
Call-ID regenerated on every leg           : FAILED
ICID preserved across every leg            : OK
```

**Conclusion.** Three of the four design assumptions hold on the fixed base: an allowed call
completes through both B2BUAs (`200`, released, the core saw the translated number
`013800138000` under rule `R-MOB-CM-40`), a `608` reject never reaches AS-2 or the core, and
the end-to-end ICID survives every hop. The fourth now reads correctly and **localises the
remaining defect**: `core Call-ID` differs from `AS-2 trunk Call-ID` by exactly `-b2b_1`,
proving AS-2 regenerates, while `AS-2 trunk Call-ID` still **equals** `S-CSCF Call-ID`,
proving AS-1 does not. That is finding (A) measured, not argued. The ICID row is the
measurement that **refuted the first pass's decision 4**.

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
  implementation of chaining. The **only** code P9's implementation stage changes is the
  anti-fraud controller's outbound `Call-ID` (decision 2) — a defect fix, not chaining.
- **A chained call is three per-instance traces, not one.** Each instance keys its trace on
  the `Call-ID` it saw on its trunk leg, and those values differ, so there is no shared key.
  The demo prints the distinct values, and the gap is registered (decision 4). The
  end-to-end ICID **is** on the wire and preserved, but no surface is keyed on it, so it does
  not make the traces correlate today.
- **A reject is observable as an absence.** The chain's short-circuit property is asserted by
  what AS-2 and the core did *not* receive, which is stronger evidence than a status code.
- **The chain exposes the two next-hop mechanisms.** That AS-1 relays to a configured peer
  while AS-2 routes by catalogue is the concrete friction P10 inherits, and it is why the demo
  has to rewrite catalogue ports.
- **The dialog identity is the controller's responsibility.** Nothing in the stack does it for
  a self-written controller, and the same omission was made twice — the strongest single
  argument for extracting the relay shell into the platform library (P10).
- **`make demo-chained` is a structural change.** It obliges `AGENT.md` section 10,
  `README.md` and `docs/README.md` to be updated in the implementation commit
  (`AGENT.md` section 13).
- **The probe is the regression guard.** Any future controller that forgets to derive the
  outbound `Call-ID`, or a sippy upgrade that changes `UacStateIdle`, turns the probe red.

## Gaps accepted

Each of the following is destined for `docs/production-gaps.md` in the **implementation
commit** — stated here, not registered now, because the register records behaviour that
exists.

- **No iFC / ISC emulation.** The mock drives the chain as a direct trunk call; a real
  deployment triggers each AS from the S-CSCF by iFC and applies Initial Filter Criteria to
  route one AS's output into the next. Production: model the S-CSCF trigger and the iFC that
  inserts a second AS in the chain.
- **No cross-AS trace correlation.** `Call-ID` cannot correlate across two B2BUAs once each
  leg regenerates it (decision 4), and although the standard end-to-end key — the
  `P-Charging-Vector`'s ICID — **is** passed through the whole chain (measured), no
  observability surface is keyed on it: both instances key their trace, log, metrics and
  console feed on the `Call-ID` of their own trunk leg. The mock's ICID is also a
  per-scenario literal (`poc-{scenario.name}`), not a per-call identity, so it proves
  pass-through but does not identify a call. Production: key the trace and console on the
  ICID, with a per-call ICID generated by the S-SBC.
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