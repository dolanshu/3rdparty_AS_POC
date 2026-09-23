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
call-rate window and block/allow lists; the output is *allow* (the INVITE is relayed as a
B2BUA — decision 6 states exactly what is copied) or *reject*.

The three dimensions that make it orthogonal to number translation:

| Dimension | Number translation (Phase 1) | Anti-fraud AS (P8) |
| --- | --- | --- |
| State | none — each INVITE is decided alone | **cross-call** — rate window and reputation decay span calls |
| Data source | the routing rule file | a **separate, operator-supplied** list/reputation source — external to the AS's own logic: a local data file in the POC, a service in production |
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
`Call-Info` is what section 6 recommends rather than a corner cut. **Section 3.3** is the
counterpart on the UAC side: a conforming UAC **MUST** include `sip.608` in the INVITE's
`Feature-Caps`. The three sections together describe one negotiation — §3.1 (when
`Call-Info` is mandatory), §3.3 (what the UAC declares) and §3.4 (how the response is sent
and who plays the announcement) — so §3.1 and §3.3 are cited here to show the omission is
**lawful under the RFC**, not a shortcut taken around it. The `jCard`/`JWS` redress
mechanism is therefore deferred to an optional enhancement.

### 5. The reject path always answers `608`; `Feature-Caps` sets the announcement obligation

The reject path is **unconditional**: the AS always answers a rejected INVITE with `608`,
whether or not the UAC declared `sip.608`. RFC 8688 section 3.4 requires the `608` to be
forwarded **as the final response to the INVITE** even when an announcement is played, and
places the announcement duty on the element that inserts the `sip.608` capability token.
The declaration therefore changes *who owes the caller an announcement*, **not** which
status code the caller receives. Branching to a different code when `sip.608` is absent
would contradict section 3.4 and would misreport an automated anti-fraud decision as
something else.

The three RFC 8688 obligations that surround the code:

| Section | Obligation |
| --- | --- |
| **§3.1** | `Call-Info` **MUST** be included unless there are indicators the caller would use the contents for malicious purposes — rejected calls are exactly those with such indicators (Decision 4) |
| **§3.3** | A conforming UAC **MUST** include `sip.608` in the INVITE's `Feature-Caps` — the counterpart of the declaration, and why the mock UAC sends it |
| **§3.4** | The `608` is forwarded as the final response **regardless**, and the element that inserts `sip.608` owns the announcement |

**What this means for a signalling-only AS.** The mock S-SBC's UAC side declares
**`Feature-Caps: *;+sip.608`** in its INVITE. In the POC the UAC has declared support, so
the section 3.4 announcement obligation **does not arise** and the reject path stays
media-free — which keeps ADR-0006 intact: no RTP stream, no MRF interaction, no announcement
port. When a **real**
UAC does not declare `sip.608`, the announcement obligation is **unmet** — this AS cannot
play one — but the AS **still answers `608`**. That is the registered gap, not a different
status code.

**The gap is made observable.** Because the obligation differs with the declaration while
the behaviour does not, the AS records the declaration state on every INVITE it screens
(`sip_608_declared: true|false`, `docs/architecture/lld.md` section 9). The declaration is
therefore visible in the Call-ID keyed trace and in the structured log, so a reviewer sees
which calls the AS answered without being able to meet §3.4's announcement duty, instead of
that distinction disappearing.

**Interoperability assumption — not verified.** In a real IMS the `Feature-Caps` header
originates at the **UAC** and has to be passed through by the S-SBC for this AS to see it
(RFC 3261 section 16.6, proxy behaviour). The POC cannot demonstrate that hop: the mock
UAC, the mock S-SBC and the AS all run the same sippy stack on loopback, so the declaration
arrives end-to-end by construction and the pass-through is untested. It is recorded below
and in `docs/production-gaps.md` as an **assumption**, not as verified behaviour.

### 6. The allow path adds no header

There is **no standard signalling mechanism** for marking a suspicious-but-allowed call
other than STIR's `verstat`, which is out of scope. Adding a proprietary header would break
the verbatim pass-through rule of ADR-0006 for no normative gain. The verdict is still
observable — through counters, the Call-ID keyed trace and the console — so no information
is lost, only kept off the wire.

**What "adds no header" means precisely.** An INVITE on the allow path is relayed as a
B2BUA, so "unchanged" has to be read against the B2BUA boundary rather than in general. The
relayed INVITE keeps the Request-URI (the called number is never rewritten) and the SDP
body, and the **pass-through header set**
(`as_app.sip_adapter.PASSTHROUGH_HEADERS`) is copied exactly as the number-translation AS
copies it; everything else is regenerated by the stack or owned by the AS.
**`Feature-Caps` is not in that set**, so a UAC's `sip.608` declaration does not cross this
AS: what survives is what the pass-through set defines, not the message in general. That is
an accepted gap (below, and in `docs/production-gaps.md`), stated here so the claim stays
accurate at the boundary instead of reading as "the whole message is untouched".

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
**no** plugin protocol and **no** shared base class. *(Mechanism updated by P10 / ADR-0009:
those modules now live in the `as_platform` library and `anti_fraud_as` imports them from
there. The substance of this decision — a second process, not a framework — is unchanged.)*

The interface between the two AS instances is deliberately **not** designed here: the
extraction into a shared library (P10) needs the friction of the second instance and of the
chained demo (P9) as its input. Direct import now is the opposite of premature abstraction
(`AGENT.md` section 12) — it defers the interface decision until there is a second real
user. `docs/architecture/lld.md` section 9 lists exactly which parts are shared, which stay
use-case-specific and which are duplicated on purpose.

## Verified facts (measured on this machine, 2026-09-19)

sippy behaviour is observed, never assumed (`AGENT.md` section 6). Two design assumptions
were settled by running the stack; the output below is a real run, not an expectation.

### The `608` reject path really works over UDP

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

Observed output (ports and Call-ID are ephemeral and vary per run; the rest is verbatim):

```text
python      : 3.10.12
sippy       : 2.4.2
stack port  : 127.0.0.1:45872  (client port 47528)
reject      : 608 Rejected  via CCEventFail((status, phrase, None))
--- INVITE sent -------------------------------------------------
INVITE sip:+8613800138000@127.0.0.1:45872;user=phone SIP/2.0
Via: SIP/2.0/UDP 127.0.0.1:47528;branch=z9hG4bK608probe0001;rport
Max-Forwards: 70
From: <sip:+86216180001@127.0.0.1>;tag=608probe-from-0001
To: <sip:+8613800138000@127.0.0.1>
Call-ID: 608probe-30165@example.invalid
CSeq: 1 INVITE
Contact: <sip:127.0.0.1:47528>
Feature-Caps: *;+sip.608
Content-Length: 0
--- responses received -------------------------------------------
[1] SIP/2.0 100 Trying
Via: SIP/2.0/UDP 127.0.0.1:47528;branch=z9hG4bK608probe0001;rport=47528
From: <sip:+86216180001@127.0.0.1>;tag=608probe-from-0001
To: <sip:+8613800138000@127.0.0.1>
Call-ID: 608probe-30165@example.invalid
CSeq: 1 INVITE
Server: AS POC anti-fraud probe
Content-Length: 0
[2] SIP/2.0 608 Rejected
Via: SIP/2.0/UDP 127.0.0.1:47528;branch=z9hG4bK608probe0001;rport=47528
From: <sip:+86216180001@127.0.0.1>;tag=608probe-from-0001
To: <sip:+8613800138000@127.0.0.1>;tag=c011c5ca806da8f273df0e04dc753797
Call-ID: 608probe-30165@example.invalid
CSeq: 1 INVITE
Server: AS POC anti-fraud probe
Content-Length: 0
handler: CCEventTry -> CCEventFail((608, 'Rejected', None))
--- verdict --------------------------------------------------------
final status line: SIP/2.0 608 Rejected
expected         : SIP/2.0 608 Rejected
CCEventFail 608 'Rejected' reject path: OK
```

**Conclusion.** sippy emits an arbitrary 6xx through `CCEventFail((status, phrase, None))`
over real UDP: the answering leg turned the event into `SIP/2.0 608 Rejected` on the wire.
The design assumption behind the reject path holds, and the implementation can rely on it.
The probe compares the whole status line — **code and reason phrase** — and exits non-zero on
any mismatch, so it is a guard rather than a printout.

**sippy emits the phrase verbatim.** A second run with `--status 608 --phrase Decline`
produced `SIP/2.0 608 Decline`, i.e. the stack does **not** normalise the reason phrase
through a status-code table; it puts on the wire exactly the phrase the caller supplied.
The consequence for the design is direct: the production reject path is the only thing that
can get the phrase right, so `AsError.sip_phrase` must resolve `608` to `Rejected` —
which is why `SIP_PHRASES` has to gain the `608` entry (`docs/architecture/lld.md`
section 9.5). Without it the caller would see `SIP/2.0 608 Server Internal Error`.

### `Feature-Caps` leaves the mock as `Feature-caps`

`Feature-Caps` is not a header sippy has a dedicated class for, so it is rendered by
`SipGenericHF`, whose `getCanName()` returns `name.capitalize()` — it capitalises **only the
first letter**. The on-wire spelling is therefore *not* the spelling written in
`src/s_sbc_mock/uac.py`.

The `608` probe above **cannot** evidence this: it hand-writes its INVITE on a plain UDP
socket, so its `Feature-Caps` line is the probe's own text rather than sippy's rendering.
The evidence comes instead from running the **real mock UAC** through the real stack and
reading the message the receiving side got. Reproducible with the committed capture tool:

```bash
uv run python tools/capture_call.py --output-dir captures/probe
grep -rin 'feature-caps' captures/probe/
```

Observed:

```text
captures/probe/01-in-invite-trunk.txt:18:Feature-caps: *;+sip.608
```

The captured file is the INVITE as it arrived at the AS, verbatim (header block; the ports
and Call-ID are ephemeral):

```text
INVITE sip:+8613800138000@127.0.0.1:45573 SIP/2.0
Via: SIP/2.0/UDP 127.0.0.1:48693;rport;branch=z9hG4bKa0ded27260b940285d6787c2ac61b2b6
Max-Forwards: 70
From: <sip:+86216180001@127.0.0.1>;tag=44219a443794445067ac659605ad6ef0
To: <sip:+8613800138000@127.0.0.1>
Call-ID: e7a6992929daac36ec40bd5d63903d0f
CSeq: 779528955 INVITE
Contact: <sip:+86216180001@127.0.0.1:48693>
Expires: 300
User-Agent: 3rd-party AS POC mock S-SBC
P-Asserted-Identity: <sip:+86216180001@ims.example.invalid>
P-charging-vector: icid-value=poc-office-to-mobile;icid-generated-at=ims.example.invalid
P-visited-network-id: ims.example.invalid
Privacy: none
Subject: office-to-mobile
Organization: office-to-mobile
Priority: normal
Feature-caps: *;+sip.608
Content-Type: application/sdp
Content-Length: 230
```

So:

```text
declared in src/s_sbc_mock/uac.py : "Feature-Caps: *;+sip.608"
on the wire from the mock UAC     : "Feature-caps: *;+sip.608"
```

`captures/` is gitignored, so the command is the artefact, not the file; nothing captured
is committed.

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

- **The RFC 8688 section 3.4 announcement obligation is unmet for a UAC that does not
  declare `sip.608`.** The AS still answers `608` — the obligation is *not met*, not avoided,
  and it is visible rather than silent: the declaration is recorded as `sip_608_declared` on
  every screened INVITE (Decision 5). Production: play the announcement, or accept traffic
  only from UACs that declare `sip.608`.
- **`Feature-Caps` pass-through by the S-SBC is assumed, not verified (interoperability).**
  In a real IMS the `sip.608` declaration originates at the UAC and must be forwarded by the
  S-SBC to reach this AS (RFC 3261 section 16.6, proxy behaviour). The POC's mock UAC, mock
  S-SBC and AS share one sippy stack on loopback, so the hop that has to pass the header
  through is not exercised and the declaration arrives by construction (Decision 5).
  Production: verify that the S-SBC forwards `Feature-Caps` unchanged before relying on the
  declaration.
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
  capitalised (*Verified facts*, `Feature-Caps` leaves the mock as `Feature-caps`).
  Cosmetic and RFC-conformant, but a byte-for-byte
  conformance test against a real S-SBC would see it.
- **`Feature-Caps` does not cross the AS on the allow path.** The pass-through header set
  does not contain `Feature-Caps`, so a UAC's `sip.608` declaration is dropped when the call
  is relayed (decision 6). The number-translation AS behaves the same way for the same
  reason; widening the shared set is not a change to make silently from here. Production:
  decide per deployment whether `Feature-Caps` is a pass-through header — it is a capability
  negotiation between the endpoints, and this AS terminates the INVITE rather than proxying
  it — and if so add it deliberately.
- **A missing calling identity fails open — security-relevant.** An INVITE without any
  calling-party identity cannot be screened. The POC deliberately **allows** it and records
  `identity_present=false` rather than rejecting, because no attestation mechanism is in
  scope (STIR is out of scope, Decision 7) and rejecting on a missing optional header would
  break legitimate traffic. Production: screen on a network-provided identity or on STIR
  attestation, or fail closed.
