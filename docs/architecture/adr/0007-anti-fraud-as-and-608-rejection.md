# ADR-0007: Anti-fraud AS — use case, `608 Rejected` semantics and state ownership

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** project maintainer
- **Related:** `docs/phase2-plan.md` section 2 (D4, D5, D9) and section 3 (P8) ·
  RFC 8688 · RFC 8197 · RFC 3261 section 7.3.1 · ADR-0001 (sippy) · ADR-0006
  (signalling only) · `docs/requirements/functional-and-nonfunctional.md`
  (REQ-F-016…REQ-F-024, REQ-NF-011…REQ-NF-015) · `docs/architecture/hld.md` section 8 ·
  `docs/architecture/lld.md` section 9 · `docs/specs/index.md`

## Context

Phase 1 delivered one AS use case: **stateless · single-leg · pure rewrite** — decide once
from the called number, rewrite the Request-URI, originate a second leg. Phase 2 opens with
a second use case, because `docs/phase2-plan.md` D2 argues that abstraction is induction
and therefore needs two instances before it can be attempted.

This ADR records the design reasoning behind the second use case: **why this use case**,
**why it rejects with `608`**, and **where its cross-call state lives**. It is a design-stage
artefact, not a requirement — the requirements are the `REQ-*` rows cited above; this
document records why P8 asks for them.

Three questions had to be settled before any code exists:

1. **The use case** — D4 picks it by *orthogonality*, not novelty. The selection criterion
   is that the second instance must exercise dimensions the first has none of; a second
   use case isomorphic to number translation would give two identical samples and the
   eventual abstraction would be shaped around one of them.
2. **The rejection semantics** — an anti-fraud AS exists to produce a *verdict about the
   caller*. The way that verdict leaves the AS on the wire is the whole external behaviour
   of the item, so it has to be chosen deliberately against the RFCs and defended, not
   picked as "the obvious 403".
3. **The ownership of cross-call state** — the item introduces state that survives a call,
   which no part of the Phase 1 design has. The most likely mistake is structural, and it
   fails silently (see *Decision 7*).

`docs/phase2-plan.md` D4 also fixes a hard filter: ADR-0006 makes the AS **signalling
only**. Every use case that needs a media plane (IVR, announcements, recording,
transcoding, DTMF, conferencing) is excluded without discussion, because adopting one would
overturn the no-RTP design and the whole chain of decisions built on it.

## Decision

### 1. The use case: an anti-fraud / unwanted-call AS

The second AS inspects the **calling** party on the trunk INVITE and returns a **verdict**.
It never rewrites the Request-URI. Inputs are a caller reputation score, a per-caller
call-rate window and block/allow lists; the output is *allow* (the INVITE is relayed
unchanged) or *reject*.

The three dimensions that make it orthogonal to number translation:

| Dimension | Number translation (Phase 1) | Anti-fraud AS (P8) |
| --- | --- | --- |
| State | none — each INVITE is decided alone | **cross-call** — rate window and reputation decay span calls |
| Data source | the routing rule file | a **separate** list/reputation source |
| Decision result | rewrite the Request-URI | **reject or allow** — no rewrite at all |

Judged on topic interest as well, unwanted calls are the dominant abuse problem for
operators, so the use case carries its own narrative (`docs/phase2-plan.md` D1: the
repository is a portfolio piece and is judged on display value).

### 2. Rejection semantics: `608 Rejected`, without `Call-Info`

A rejected call is answered on the trunk with **`608`** and the reason phrase **`Rejected`**,
in a `CCEventFail((608, "Rejected", None))` raised on the answering leg. **No `Call-Info`
header is sent.** On the allow path the relayed INVITE carries **no added header**.

### 3. Why `608`, and not `403` / `603` / `607`

RFC 8688 (Standards Track, December 2019) defines `608` and states in section 3 that the
intermediary *"could be a back-to-back user agent (B2BUA) or a SIP Proxy"* — which is
precisely this AS. The alternatives lose information that this AS exists to produce:

| Code | Why it was rejected |
| --- | --- |
| **403 Forbidden** | Semantically generic: it says "not permitted" without saying *who* decided or *why*. It discards the one piece of information this AS exists to produce — that an **automated anti-fraud engine** made the decision. |
| **607 Unwanted** (RFC 8197) | It means a **human** at the target UAS marked the call unwanted. The AS's decision is automated, so `607` would misattribute it. RFC 8688 draws that distinction deliberately, because *"in some jurisdictions, this distinction is important."* |
| **603 Decline** | It means the called party declined. It loses the same information as `403`, and it cannot answer the reviewer's question *"why not 608?"*. |

### 4. `Call-Info` is omitted lawfully, not as a shortcut

RFC 8688 section 3.1 makes `Call-Info` mandatory only when *"there are no indicators the
calling party will use the contents … for malicious purposes"*, and section 6 states that
operators *"may wish to configure their response to only include a `Call-Info` header field
for INVITE … that pass validation by STIR"* — because handing a suspected-abusive caller a
contact address gives that caller a vector for attacking the intermediary.

Calls rejected by this AS are, by definition, the *suspected-abusive* ones, so omitting
`Call-Info` is what section 6 recommends rather than a corner cut. The `jCard`/`JWS`
redress mechanism is therefore deferred to an optional enhancement.

### 5. `Feature-Caps: *;+sip.608` protects ADR-0006

RFC 8688 section 3.4 requires that when the UAC has **not** declared `sip.608`, the
intermediary **MUST play an announcement**. A signalling-only AS cannot play one. Section
3.4 also states that *"if the UAC indicates support for 608 and the intermediary issues a
608, life is good"*.

The mock S-SBC's UAC side therefore declares **`Feature-Caps: *;+sip.608`** in its INVITE.
Declaring it keeps the reject path free of media and therefore keeps ADR-0006 intact: the
AS can emit `608` without opening an RTP stream, an MRF interaction or an announcement
port. Without the declaration the AS would have to choose between two unacceptable
outcomes — play media (overturning ADR-0006) or send a `608` the UAC is not prepared to
handle.

A **real** UAC that does not declare `sip.608` would require a media announcement. That is
an **accepted gap, not a hidden defect**: it is registered below and in
`docs/production-gaps.md` in the implementation commit.

### 6. The allow path adds no header

There is **no standard signalling mechanism** for marking a suspicious-but-allowed call
other than STIR's `verstat`, which is out of scope. Adding a proprietary header would break
the verbatim pass-through rule of ADR-0006 for no normative gain. The verdict is still
observable — through counters, the Call-ID keyed trace and the console — so no information
is lost, only kept off the wire.

### 7. STIR/SHAKEN is explicitly out of scope

RFC 8224 verification needs certificate chains, attestation handling and `Identity` header
parsing. RFC 8688 is a parallel and complementary mechanism that does not depend on it.
Excluding STIR is a **scope decision, stated here so that a reviewer does not read it as an
oversight**: the anti-fraud AS demonstrates the *verdict and reject* path, not call
authentication. A production AS would use the `Identity` header's attestation as one more
screening signal.

### 8. Ownership of cross-call state (D9)

Anti-fraud state lives in a **process-level module, strictly separate from the per-call
`CallController`**. It is **in-memory only**; a restart loses it. **Redis is deferred to
P11**, where it becomes the second implementation of the platform's pluggable state store.

Ownership first, because this is the item's most likely silent failure: `CallController` is
instantiated **per call**, so a rate window held there would always contain exactly one
entry — the logic would fail silently and single-call unit tests would still pass. Naming
the boundary now is cheaper than debugging it later. The boundary is drawn in
`docs/architecture/lld.md` section 9: the store is process-level, the controller is
per-call, and the controller sees the store only through plain, already-computed values.

The verdict itself stays a **pure function** (REQ-NF-011): no sockets, no global state, no
clock access inside the screening engine. Time is **injected**; the state store is the only
place a clock is read, and it is given one.

**Why "restart loses state" is deliberately left open.** It is not merely a defect to
tolerate — it is part of the argument for why the platform must offer a pluggable state
store, and closing it in P8 would remove one of the reasons P10 exists. In-memory also
keeps the property this repository values most: a clean checkout reaches `make demo` fully
offline with no external service.

### 9. A second process, not a framework

P8 builds a **second concrete AS**: a separate process (`python -m anti_fraud_as.main`)
with its own SIP listen ports, its own declarative data file under `config/`, its own
console feed and its own lifecycle. It reuses the **existing, use-case-agnostic modules** of
`as_app` by direct import — the error model, structured logging, counters, tracing, the
generic parts of `sip_adapter`, and the signal/port plumbing. It introduces **no** registry,
**no** plugin protocol and **no** shared base class.

The interface between the two AS instances is deliberately **not** designed here: the
extraction into a shared library (P10) needs the friction of the second instance and of the
chained demo (P9) as its input. Direct import now is the opposite of premature abstraction
(`AGENT.md` section 12) — it defers the interface decision until there is a second real
user. `docs/architecture/lld.md` section 9 lists exactly which parts are shared, which stay
use-case-specific and which are duplicated on purpose.

## Verified facts (measured on this machine, 2026-09-19)

sippy behaviour is observed, never assumed (`AGENT.md` section 6). Two design assumptions
were settled by running the stack; the output below is a real run, not an expectation.

### 5.1 The `608` reject path really works over UDP

`404` and `603` were already proven by the Phase 1 error branches; `608` was not. The probe
is committed as **`tools/anti_fraud_probe.py`** and is a design instrument, in the
precedent of `tools/sippy_probe.py`. It starts the same primitives the AS runs (`SipConf`,
`SipTransactionManager`, `ED2.loop()`, one `UA` per INVITE), terminates one INVITE on its
answering leg and fails it with `CCEventFail((608, "Rejected", None))` — the same call
`CallController` makes for its reject path.

Command:

```bash
uv run python tools/anti_fraud_probe.py
```

Observed output (ports are ephemeral and vary per run; the rest is verbatim):

```text
python      : 3.10.12
sippy       : 2.4.2
stack port  : 127.0.0.1:45894  (client port 47246)
reject      : 608 Rejected  via CCEventFail((status, phrase, None))
--- INVITE sent -------------------------------------------------
INVITE sip:+8613800138000@127.0.0.1:45894;user=phone SIP/2.0
Via: SIP/2.0/UDP 127.0.0.1:47246;branch=z9hG4bK608probe0001;rport
Max-Forwards: 70
From: <sip:+86216180001@127.0.0.1>;tag=608probe-from-0001
To: <sip:+8613800138000@127.0.0.1>
Call-ID: 608probe-93364@example.invalid
CSeq: 1 INVITE
Contact: <sip:127.0.0.1:47246>
Feature-Caps: *;+sip.608
Content-Length: 0
--- responses received -------------------------------------------
[1] SIP/2.0 100 Trying
Via: SIP/2.0/UDP 127.0.0.1:47246;branch=z9hG4bK608probe0001;rport=47246
From: <sip:+86216180001@127.0.0.1>;tag=608probe-from-0001
To: <sip:+8613800138000@127.0.0.1>
Call-ID: 608probe-93364@example.invalid
CSeq: 1 INVITE
Server: AS POC anti-fraud probe
Content-Length: 0
[2] SIP/2.0 608 Rejected
Via: SIP/2.0/UDP 127.0.0.1:47246;branch=z9hG4bK608probe0001;rport=47246
From: <sip:+86216180001@127.0.0.1>;tag=608probe-from-0001
To: <sip:+8613800138000@127.0.0.1>;tag=37a6f743dd178ae6ba1b7b09325da5b0
Call-ID: 608probe-93364@example.invalid
CSeq: 1 INVITE
Server: AS POC anti-fraud probe
Content-Length: 0
handler: CCEventTry -> CCEventFail((608, 'Rejected', None))
--- verdict --------------------------------------------------------
final status line: SIP/2.0 608 Rejected
CCEventFail 608 reject path: OK
```

**Conclusion.** sippy emits an arbitrary 6xx through `CCEventFail((status, phrase, None))`
over real UDP: the answering leg turned the event into `SIP/2.0 608 Rejected` on the wire.
The design assumption behind the reject path holds, and the implementation can rely on it.
The probe exits non-zero when the observed status line does not carry the requested code, so
it is a guard rather than a printout.

### 5.2 `Feature-Caps` leaves the mock as `Feature-caps`

`Feature-Caps` is not a header sippy has a dedicated class for, so it is rendered by
`SipGenericHF`, whose `getCanName()` returns `name.capitalize()` — it capitalises **only the
first letter**. The on-wire spelling is therefore *not* the spelling written in
`src/s_sbc_mock/uac.py`:

```text
declared in src/s_sbc_mock/uac.py : "Feature-Caps: *;+sip.608"
rendered by sippy                 : "Feature-caps: *;+sip.608"
```

Measured by running the mock UAC through the real stack and reading the bytes the AS
received (the same path `tools/capture_call.py` uses); the inbound INVITE carried:

```text
Feature-caps: *;+sip.608
```

**This is not a defect.** RFC 3261 section 7.3.1 makes header field names
**case-insensitive**, so `Feature-caps` and `Feature-Caps` are the same header field, and
the value `*;+sip.608` is unchanged. It is the same cosmetic caveat the LLD already records
for `P-Charging-Vector` → `P-charging-vector` (`docs/architecture/lld.md` section 2.3); the
two observed samples (`P-charging-vector`, `P-visited-network-id`) show it is systematic,
not specific to this header. It is recorded here as an **accepted caveat**: the RFC 8688
capability token is present and correctly valued, only the casing of its name differs.
The integration layer asserts the spelling that actually goes on the wire, not the spelling
in the source.

## Consequences

- **The reject path is UAS-only.** A rejected call never originates a second leg: it is
  terminated on the trunk and answered there. This relaxes the two-leg assumption of
  `CallController` (M1 design), which the skeleton has to tolerate — `uaA` may be the only
  leg for the whole lifetime of a call. It follows that the reject path adds **no** outbound
  transaction and therefore no new retransmission population (the P8a consequence).
- **The allow path is still a B2BUA.** It relays `INVITE → 100 → 180 → 200 OK → ACK → BYE`
  with the Request-URI and the headers unchanged, so REQ-F-002's "B2BUA only" statement
  continues to describe it; REQ-F-021 records the documented deviation for the reject path.
- **The verdict is observable, not signalled.** Counters, the Call-ID keyed trace and the
  console carry the verdict, the signals and the score; the wire carries none of them.
- **Cross-call state dies with the process.** Deliberate (Decision 8), and the reason P11's
  pluggable state store exists.
- **A second process needs its own identity pinning and its own stop path.** `SipConf` and
  `ED2` are process-wide singletons, and every timer the new process arms must be cancelled
  from its own stop path (P8a lesson 5). The LLD section 9 process model states this.
- **The second AS is evidence for P10, not the platform.** Nothing in P8 is designed for
  reuse by a third use case; the friction the chained demo (P9) produces is what P10 turns
  into an interface.

## Gaps accepted

Each of the following is destined for `docs/production-gaps.md` in the **implementation
commit** — stated here, not registered now, because the register records behaviour that
exists.

- **No media announcement for a UAC that does not declare `sip.608`.** RFC 8688 section 3.4
  requires one; a signalling-only AS cannot provide it (Decision 5). Production: play the
  announcement, or refuse to emit `608` towards such a UAC.
- **No `Call-Info` / `jCard` / `JWS` redress mechanism.** Lawful under RFC 8688 section 6
  (Decision 4), but a production AS serving a jurisdiction that mandates redress would need
  it.
- **Cross-call state is in-memory and lost on restart**, and cannot be shared by several AS
  instances (Decision 8). Closed in P11 by the pluggable state store.
- **No STIR/SHAKEN attestation as a screening input** (Decision 7). Production would use the
  `Identity` header attestation as one more signal.
- **No external reputation service.** Reputation is seeded from the declarative data file
  and decayed locally; querying a live NPDB/reputation feed on the call path would need the
  same loop-owned, non-blocking treatment as the data-file reload.
- **No per-caller eviction policy.** The in-memory state is bounded by a configured maximum
  tracked callers; a production node needs a TTL and an eviction strategy.
- **Header-name casing.** `Feature-caps` leaves the mock with the first letter only
  capitalised (Verified facts 5.2). Cosmetic and RFC-conformant, but a byte-for-byte
  conformance test against a real S-SBC would see it.
- **A missing calling identity fails open.** An INVITE without any calling-party identity
  cannot be screened; the POC allows it and records that it could not screen. Production
  would use network-provided identity or reject.
