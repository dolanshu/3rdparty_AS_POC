# Phase 2 plan — second AS use case and the generic AS platform

- **Status:** accepted (planning artefact, no implementation yet)
- **Date:** 2026-09-18
- **Owner:** project maintainer
- **Related:** `AGENT.md` §2, §14 rule 3, §15 · `docs/roadmap.md` · `docs/production-gaps.md` · `docs/specs/index.md`

## 1. Purpose and scope of this document

The POC is complete: M0–M4 are done and the post-M4 items P1–P7 are closed except P4
(browser verification, parked) and P6 (sippy retransmission-timer shutdown, see P8a below).
This document records **what comes next and why**.

It is written as a **handover artefact**. `AGENT.md` §15 requires that a fresh conversation
must not have to re-derive what an earlier one decided, and states plainly that
*"conversation context is not a handover artefact"*. Every decision below therefore carries
its rationale, not just its outcome. A conversation that starts a Phase 2 work item should
read `AGENT.md`, `docs/README.md`, **the section of this document for that item**, and the
acceptance criteria — and then be able to start.

**Single source of truth.** This document is the *only* detailed source for Phase 2.
`docs/roadmap.md` carries one status line per item and links here; it does **not** duplicate
the content. Two copies of a plan drift apart exactly the way
`config/routing_rules.yaml` and `config/routing_rules.compose.yaml` do, and that drift is
already registered as a production gap. Do not repeat that mistake.

**Out of scope here:** the state of M0–M4 and P1–P7 (see `docs/roadmap.md`), and anything
already recorded in `docs/production-gaps.md`.

## 2. Strategic decisions

### D1 — The purpose is a portfolio piece, not a product

**Decision.** The repository exists to demonstrate capability to architecture reviewers and
to operator-side and employer audiences. Display value outranks functional completeness.

**Rationale.** `AGENT.md` §1 already states *"This project exists to be reviewed."* The
investment profile of the repository — the document chain, the ADRs, the acceptance
evidence, the production gap register — is the shape of something built to be reviewed, not
of something built to be sold. Number translation itself has weak commercial logic: every
S-CSCF/SBC vendor and every enterprise PBX already ships it, so no operator would buy a
standalone third-party number-translation AS. What the repository sells is the engineering,
not the feature.

**Consequence.** Every later decision is judged on display value and on what it adds to the
platform story, never on production completeness for its own sake.

### D2 — Direction: second use case first, then the platform

**Decision.** Build a second AS use case, then extract the common skeleton into a generic
platform. Rejected: completing the production gap register into a commercial product (D3
reframes that option rather than dropping it); building the platform directly from the single
existing sample; and abandoning this line of work for an unrelated project in another domain.

**Rationale.** Abstraction is induction and needs at least two instances. Extracting a
framework from one sample produces a framework shaped like that sample — here, like number
translation — which is a different thing from a framework shaped like an AS. `AGENT.md` §12
forbids exactly this (*"no abstraction added because production would need it"*). Building
the second use case first also means the skeleton is exercised twice before it is
generalised, which is what makes the generalisation credible.

**Why not start something unrelated instead?** The fourth option considered was to stop and
begin an unrelated project in a different domain. That is a *breadth* strategy and it
conflicts with D1: a portfolio piece gains more from visible depth in one domain than from a
second shallow artefact, and everything already accumulated here — the document chain, the
ADRs, the acceptance evidence, a working three-service stack — would be abandoned rather
than compounded.

### D3 — The gap register is repositioned, not abandoned

**Decision.** The production gap register is **not** a backlog to be completed. Selected
items are adopted only when they **feed the platform**: either as an input that reveals what
the abstraction must support, or as an output that proves the abstraction was right.

**Rationale.** Completing all ~24 registered gaps is months of engineering that adds almost
no display value — a reviewer does not become excited by the presence of TLS support — and
it would turn a clean POC into a half-finished product, which is the worst of both shapes.
Reframing the question from *"is this needed in production?"* to *"does this drive or verify
the platform?"* turns the register from dead weight into a source of requirements.

**Consequence.** Two categories, and the distinction matters for sequencing:

- **Discovery inputs** — must run *before* the abstraction, because the answer is not known
  until measured: the capacity probe (P9.5).
- **Verification outputs** — run *after* the abstraction, to prove it was right: TLS (P11).
  Trunk TLS is already fully specified in the gap register, so building it early would teach
  nothing new; its value is in demonstrating that transport really is pluggable.

### D4 — Second use case: anti-fraud / unwanted-call AS

**Decision.** The second AS inspects the **calling** party and returns a **verdict**, not a
rewrite. Inputs: caller reputation, a per-caller call-rate window, and block/allow lists.
Outputs: allow (relay unchanged) or reject.

**Rationale — the selection criterion was orthogonality, not novelty.** The first use case
has an exact shape: *stateless · single-leg · pure rewrite* (decide once, rewrite the
Request-URI and number format). A second use case with the same shape would give two
isomorphic samples and the abstraction would come out wrong. This one introduces three
dimensions the first has none of:

| Dimension | Number translation | Anti-fraud AS |
| --- | --- | --- |
| State | none, per-INVITE only | **cross-call** (rate window, reputation decay) |
| Data source | the rule file | **external** list/reputation source |
| Decision result | rewrite the Request-URI | **reject** or allow — no rewrite at all |

Judged against topic interest as well, unwanted calls are the dominant abuse problem for
operators worldwide, so the use case carries its own narrative.

**ADR-0006 is a hard filter.** The service is signalling only. Every use case needing a
media plane — IVR, auto-attendant, recording, transcoding, conferencing, DTMF — is excluded
without discussion, because adopting one would overturn ADR-0006 and the whole no-RTP design
around it.

### D5 — Rejection is `608 Rejected` (RFC 8688), without `Call-Info`

**Decision.** Reject with **608** — not 403, not 603, not 607. No `Call-Info` header is
sent. The mock SBC's UAC side must send `Feature-Caps: *;+sip.608` in its INVITE. On the
allow path the INVITE is relayed with **no added header**; the suspicion score is exposed
only through metrics, trace and console.

**Rationale.** RFC 8688 (Standards Track, December 2019) defines 608 and states in §3 that
the intermediary *"could be a back-to-back user agent (B2BUA) or a SIP Proxy"* — precisely
this AS.

- **403 Forbidden** was rejected as semantically generic: it says "not permitted" without
  saying *who* decided or *why*, so it discards the one piece of information this AS exists
  to produce — that an automated anti-fraud engine made the decision.
- **607 Unwanted (RFC 8197)** means a **human** at the target UAS marked the call unwanted.
  This AS is an automated decision, so 607 would misattribute it. RFC 8688 draws the
  distinction deliberately, because *"in some jurisdictions, this distinction is important."*
- **603 Decline** was rejected: it means the called party declined, and it loses the
  information that an automated anti-fraud engine made the decision. It would also be unable
  to answer the reviewer's question *"why not 608?"*.

**`Call-Info` is omitted lawfully, not by cutting a corner.** RFC 8688 §3.1 makes
`Call-Info` mandatory only when *"there are no indicators the calling party will use the
contents … for malicious purposes"*, and §6 states that operators *"may wish to configure
their response to only include a `Call-Info` header field for INVITE … that pass validation
by STIR"*, because handing a suspected-abusive caller a contact address gives that caller a
vector for attacking the intermediary. Calls rejected by this AS are by definition the
suspected-abusive ones, so omitting `Call-Info` is what §6 recommends. The `jCard`/`JWS`
redress mechanism is therefore deferred to an optional enhancement (see §7).

**`Feature-Caps` protects ADR-0006.** RFC 8688 §3.4 requires that when the UAC has *not*
declared `sip.608`, the intermediary **MUST play an announcement** — which this
signalling-only service cannot do. §3.4 also states that *"if the UAC indicates support for
608 and the intermediary issues a 608, life is good"*. Having the mock UAC declare
`Feature-Caps: *;+sip.608` therefore keeps the AS media-free. A real S-SBC that does not
declare it would require media; that is a registered gap, not a hidden defect.

**Allow path adds no header.** No standard signalling mechanism exists for marking a
suspicious-but-allowed call other than STIR's `verstat`, which is out of scope (D4). Adding
a proprietary header would break the verbatim pass-through rule of ADR-0006 for no
normative gain. The verdict is still observable — through counters, the Call-ID keyed trace
and the console — so no information is lost, only kept off the wire.

**STIR/SHAKEN is out of scope.** RFC 8224 verification needs certificate chains,
attestation handling and `Identity` header parsing. RFC 8688 is a parallel and complementary
mechanism that does not depend on it. Excluding it is a scope decision, not a defect, and
the ADR for the use case must say so explicitly because a reviewer will ask.

### D6 — Two independent AS processes; the chained demo comes before the abstraction

**Decision.** The anti-fraud AS is a **separate process** with its own rules, ports and
console feed. Both AS instances are demonstrated independently first. A chained topology
(`SBC → AS-1 → AS-2 → core`) is built **before** the platform work starts, not after.

**Rationale.** Independent processes are the architecturally real shape: in IMS, several AS
instances are triggered in sequence by iFC priority over ISC (3GPP TS 24.229). It also gives
the abstraction a genuine second instance — independent process, independent decision logic,
shared skeleton — which is what the platform story needs.

The chained demo exists to **generate friction deliberately**. Driving both AS instances in
one path is what exposes the parts of the skeleton that are secretly number-translation
specific, and that friction is the highest-quality input the abstraction can get. Without
it, the abstraction is driven by reading code instead of by real collisions.

### D7 — Public throughout, one branch per work item

**Decision.** The repository stays public. Each Phase 2 item is developed on its own branch
and merged into `main` only when the item's own definition of done is met.

**Rationale.** Under D1 visibility is the point; going private for months would produce
nothing. But `main` must always be demonstrable: `AGENT.md` §4.7 requires a green CI badge,
§4.2 a complete document set, §16 that `make demo` passes from a clean checkout, and §4.8
that *"an acceptance item without evidence is not accepted"*. Work in progress on `main`
would temporarily violate all of these, and a reviewer may arrive at any moment.

A plan may live on `main` (it is a plan, not an unfinished implementation); an **ADR for
unimplemented behaviour may not** — its *consequences* section cannot be validated before
the code exists, so it would describe functionality that is not there.

### D8 — Split the repositories in two stages

**Decision.** The anti-fraud AS is built **in this repository**. The platform is extracted
into a **new repository**; this repository then becomes the platform's reference
implementation and first user.

**Rationale.** Stage one belongs here because the anti-fraud AS reuses the mock S-BC, the
console, the three-layer test scaffolding, the whole document set and the ADRs — moving it
out would mean copying all of that. It also keeps one visible story of evolution. Stage two
belongs in a new repository because the platform needs its own identity to be referenced and
cited independently, and because the fact that *"this platform is used by two different AS
implementations"* — the strongest evidence that the abstraction was right — requires two
repositories to exist.

**Change the standard, do not lower it.** The new repository must not copy all 24 documents
of `docs/` here. It is a **library**, not a running service, so the operations set
(`deployment` / `runbook` / `troubleshooting`) does not apply; what it needs instead is an
API reference, an integration guide and a compatibility matrix. Copying the application
document set would create two drifting copies; shipping none would produce a low-standard
artefact. Switching to the standard that fits a library is neither.

**Not adopted:** converting this repository into a uv workspace monorepo. It would keep one
CI and one document set, but it would overturn the fixed top-level layout of `AGENT.md` §4.1.

### D9 — Cross-call state: in-process, and never in the call controller

**Decision.** Anti-fraud state lives in a **process-level module**, strictly separate from
the per-call `CallController`. In-memory only for now; restart loses it. **Redis is deferred
to P11**, where it becomes the second implementation of the platform's pluggable state store.

**Rationale — ownership first.** The most likely mistake is to put the rate window inside
`CallController`, because `apply_call_policy()` is a convenient existing hook.
`CallController` is instantiated **per call**, so a window held there would always contain
exactly one entry: the logic would fail silently, and single-call unit tests would still
pass. Naming the ownership boundary now is cheaper than debugging it later.

**Why Redis was proposed, and why it is not adopted here.** An external store is the
*production-correct* answer: state survives a restart and can be shared by several AS
instances, and it would have given the platform a real pluggability driver. The concrete
proposal was a Redis service in `docker compose` with the demo becoming docker-only. Three
costs outweighed it:

1. **`make demo` would stop being the golden path.** `AGENT.md` §10 puts it above feature
   work (*"If that breaks, fixing it outranks adding features"*), §16 makes it the first
   definition-of-done item, and it is the README's front door and the M4 acceptance
   evidence.
2. **The test pyramid and CI would depend on an external service.** Integration and e2e run
   in-process: `tests/conftest.py`'s `TrunkPair` fixture binds ephemeral UDP ports and shares
   one `ED2` loop, so external state means both layers need a live Redis — and CI has **no
   docker job** (`.github/workflows/ci.yml` still carries it as a commented-out TODO; see P3
   in `docs/roadmap.md`). The anti-fraud logic would become unverifiable in CI and the
   five-green-layers asset would be lost.
3. **sippy's threading constraint.** `ED2.loop()` blocks the main thread and `AGENT.md` §6
   forbids blocking work inside a sippy callback, so a synchronous Redis lookup on the call
   path would stall the whole SIP stack. It needs the same treatment as rule reload — driven
   from a loop-owned timer instead.

The dual-track compromise (in-memory for `make demo` and CI, Redis for `docker compose`) was
considered and rejected **for stage one**: it builds two store implementations before the
decision logic exists, and P8's effort belongs in the verdict algorithm — the rate window,
reputation decay and list matching — not in container orchestration. The dual-track split
reappears in P11, once the abstraction gives it a reason to exist.

**Do not solve "restart loses state" early.** That limitation is not merely a defect to
tolerate: it is part of the argument for why the platform must offer a pluggable state
store. Closing it in P8 would remove one of the reasons P10 exists.

In-memory also keeps the property this repository values most — a clean checkout reaches
`make demo` fully offline with no external service, the same principle behind the
dependency-free console and the fixed-ipam compose network. Making the store *replaceable*
now would be premature abstraction (`AGENT.md` §12); a clean class boundary is enough, and
P11 does the generalisation once two implementations are actually wanted.

### D10 — Two enhancement items, one of each kind

**Decision.** Adopt **TLS** (verification output) and a **small call-load capacity harness**
(discovery input). **CDR** was the strongest candidate not taken; it stays a *candidate*,
not a rejection — see the last paragraph of this section.

**Rationale.** TLS gives the platform a second real pluggable dimension (transport), which
matters because a single sample — the state store — cannot support a claim that anything is
"pluggable". The capacity harness targets the one area this repository has explicitly
forbidden rather than merely left undone: `AGENT.md` §2 says *"No performance or capacity
work … no benchmarking claims"* and the gap register says `Capacity | Not measured`. Filling
a hole shows more than building on flat ground.

**Why CDR was not taken, and why it may come back.** CDR generation is the only
**cross-cutting** candidate: metrics, tracing and CDRs are things every AS needs that are not
the business logic itself, and a cross-cutting framework is the most convincing thing a
platform can offer — more convincing than any single feature. It was not taken because two
enhancement items are enough for one stage, and because the capacity harness targets a hole
rather than flat ground (D3). None of that reasoning devalues CDR, so **it should be
reconsidered at P10/P11**, where "what does every AS get for free" is exactly the question
the platform must answer.

Recorded explicitly so that a later conversation does not read "not adopted" as "considered
and found wanting" — the same failure mode that would have hidden the Redis reasoning (D9).

**The harness must not publish benchmark numbers.** sippy's `ED2.loop()` is single-threaded
and blocking and the transport is UDP, so absolute figures will look weak next to any
commercial SBC, and publishing them invites questions about hardware, kernel and UDP buffer
sizing. Its purpose is a **regression baseline and a way to discover the capacity boundary**
— it is a measurement capability of the platform, not a performance claim. See §8 for the
scope change this requires.

## 3. Work sequence

`AGENT.md` §15 names M4 as the final milestone and there is no M5, so Phase 2 continues the
**P** numbering of the post-M4 items.

### P8a — Fix the sippy retransmission-timer shutdown (blocker)

- **Goal.** Cancel per-transaction retransmission timers in
  `SipTransactionManager.shutdown()`, removing the `TypeError` in `transmitData`.
- **Why now.** Currently a ~1-in-6 flake in
  `test_next_hop_failover_uses_the_second_hop`. P9.5 is a hard blocker: a load run generates
  exactly the conditions — many concurrent transactions and frequent retransmissions — that
  turn 1-in-6 into deterministic failure.
- **Notes.** `shutdown()` cancels its own `cp_timer` but not `t.teA`. The in-process tests
  share one process-wide `ED2` loop, so a stale timer from a stopped manager fires during a
  later test.
- **Type.** Bug fix. Independent branch, mergeable on its own; it makes `main` strictly more
  stable.
- **Status: done (2026-09-18)** on `fix/sippy-retransmission-timer` (branched from `main`
  at `7c4a417`). Acceptance item **ACC-P8A-001** with evidence in
  `docs/acceptance/report.md`. **Not merged and not tagged** — both are the maintainer's
  steps (§4, `AGENT.md` §13).

**Done in this conversation (2026-09-18).** Nothing under `site-packages` changed: sippy
stills ship the defect, and the repository cancels what it armed itself, from its own
`src/as_app/` — so no monkey-patching and therefore no ADR-0001 consequence to reopen.

- `as_app/sip_adapter.py` — `cancel_transaction_timers(manager)` walks both transaction
  tables (`tclient`, `tserver`) and cancels every `teA`…`teG` timer that is still
  scheduled, returning how many it cancelled. It has to run **before**
  `SipTransactionManager.shutdown()`, because that call drops the very tables the timers
  hang from.
- `as_app/main.py` — `AsStack.stop()` calls it, then `SipTransactionManager.shutdown()`
  exactly as before. This is the whole production `SIGTERM` path, so a real AS process
  that stops mid-retransmission no longer throws on the way out.
- `as_app/call_controller.py` — `TrunkCallMap.dispose()` → `CallController.dispose()`
  cancels the per-call **no-answer timer** as well. It was a second instance of the same
  bug found while probing: it survives the manager, fires into `_sip_tm` being `None` and
  raises the identical `TypeError` through `sendResponse`. Fixing the transaction timers
  alone would have left this one standing.
- Tests: 4 unit tests (`tests/unit/test_sip_adapter.py`) cover the cancellation itself —
  every armed timer cancelled once, idempotent second pass, an already fired timer is not
  counted, an already shut-down manager does not raise — and one integration test
  (`test_stopping_the_stack_leaves_no_transaction_timer_armed`) fails the moment the
  cancellation is removed, with `AssertionError: 2 timer(s) still armed on a stopped
  transaction manager`. That makes the guard deterministic rather than a repeat-the-flake
  lottery.

**What was learned — how sippy owns its timers (every later item inherits this).**

1. **The timers do not belong to the manager.** `SipTransactionManager.shutdown()` cancels
   `cp_timer`, shuts the UDP server down and then assigns `None` to `global_config`,
   `tclient`, `tserver`, `l1rcache`, `l2rcache`, `req_cb` and `req_consumers`. Anything
   that still holds a transaction fires into those `None`s. The transaction objects carry
   the timers (`teA`…`teG`) and nothing else refers to them, so **whoever stops a manager
   must walk its tables first** — there is no manager-level "cancel everything".
2. **`ED2` is the real owner of the schedule.** A `Timeout` is an `EventListener` pushed
   onto a heap that lives for the life of the process, not of the manager. Cancelling sets
   `cb_func = None` and leaves the entry in the heap; the loop skips it later. This is why
   the defect crossed test boundaries at all, and it is also the way to assert about it:
   `[el for el in ED2.tlisteners if el.cb_func is not None and el.cb_func.__self__ is manager]`
   is the authoritative list of what a manager is still scheduled to do.
3. **`timerA` re-arms itself.** `timerA()` doubles `t.tout` and creates the next `Timeout`
   from inside the callback, so cancelling once is enough only because `cancel()` runs
   before the next scheduled round; the chain has no other stop condition than `timerB`
   cancelling it (32 s by default). A client transaction towards an unreachable hop is
   therefore armed for **32 seconds** after the INVITE, whatever the application thinks it
   has given up on. P9.5 (a load run against unreachable hops) inherits exactly this
   population of armed timers.
4. **sippy swallows the exception.** `ED2.dispatchTimers()` catches everything a timer
   callback raises and prints it with `dump_exception()`. That is why this never crashed a
   single test deterministically: it costs one printed traceback per surviving timer, and
   only *sometimes* perturbs a later assertion. **A printed traceback in the middle of the
   suite is a defect, not noise** — worth remembering for every later item, because this
   class of failure does not turn red on its own.
5. **The second leak was application-owned.** Anything the repository arms with `Timeout`
   (rule reload poll, shutdown poll, the controller's no-answer timer) outlives the objects
   it was created for unless the owner cancels it. P8 adds a second AS process with its own
   rule reload and — per D9 — its own cross-call windows, so this scales with every new
   timer: **arm it where you can cancel it, and cancel it from the stop path**.

### P8 — Anti-fraud AS

- **Goal.** A second, independently runnable AS process implementing D4, D5 and D9.
- **Prerequisites.** New ADR (use-case choice, 608 rationale, state ownership). A probe
  confirming that sippy emits an arbitrary 6xx through the existing
  `CCEventFail((status, phrase, None))` path — 404 and 603 are already proven, 608 is not.
  Adding `Feature-Caps: *;+sip.608` to the mock UAC's INVITE.
- **Known collisions.** The reject path is **UAS behaviour, not B2BUA**: no second leg is
  originated. `CallController` currently assumes `uaA` and `uaO` always both exist (M1
  design), so this item **changes the skeleton itself**.
- **Also.** New `AS-FRAUD-*` error codes in `src/as_app/errors.py`, following the existing
  `AS-CFG-* / AS-RULE-* / AS-ROUTE-* / AS-PEER-*` model. Port and rule-file isolation for a
  second AS (see §7). Console coverage per `AGENT.md` §16.
- **Entry state (set by P8a, 2026-09-18).** `main` is expected to carry the timer fix, so
  the shutdown path this item inherits is clean: `AsStack.stop()` cancels what the stack
  armed, including the per-call no-answer timers, and sippy's `shutdown()` already does its
  own part. Two things follow for a **second AS process**: its own timers must be cancelled
  from its own stop path (see *how sippy owns its timers*, point 5, in P8a above), and the
  reject path is UAS-only — it never originates a leg, so this item adds **no** new
  transaction towards a next hop and therefore no new retransmission population. The
  capacity-relevant consequence of P8a is for **P9.5**: the client transactions towards
  unreachable hops stay armed for `timerB` = 32 s regardless of what the application gives
  up on, which is what a load run must expect to find.

### P9 — Chained demo

- **Goal.** `SBC → AS-1 (anti-fraud) → AS-2 (number translation) → core`, running and
  demonstrated.
- **Implementation note.** No iFC emulation is needed in the mock: pointing AS-1's next hop
  at AS-2's listen address is enough, which is a `next_hops` catalogue change.
- **Deliberate output.** The friction this surfaces — what in the skeleton turned out to be
  number-translation specific — is the primary input to P10 and must be written down here.
- **Known issue.** Two B2BUAs in series produce **two different Call-IDs**; cross-AS
  correlation is a real problem, not a cosmetic one.

### P9.5 — Read-only capacity probe

- **Goal.** Discover where the capacity boundary is. **Do not change the skeleton** — add a
  load generator plus observation only.
- **Prerequisites.** P8a merged.
- **Output.** The constraints found (concurrency ceiling, back-pressure behaviour, what
  blocks the event loop) become inputs to P10 and are registered as gaps.
- **Explicitly not:** any published calls-per-second or latency figure (D10).

### P10 — Platform extraction (new repository)

- **Goal.** Extract the skeleton shared by both AS instances into a library; both become its
  users; this repository becomes the reference implementation.
- **Inputs.** Three genuine drivers: pluggable state store (P8), skeleton friction (P9),
  capacity/back-pressure constraints (P9.5).
- **Constraints.** This is a structural refactor of `src/as_app/` and therefore requires an
  explicitly approved plan under `AGENT.md` §14 rule 3 (no unconfirmed refactors) — it
  must not be done incidentally. The new repository follows a library standard, not this
  repository's application standard (D8).

### P11 — Platform verification: pluggable transport, pluggable state store, capacity harness

- **Goal.** Prove the abstraction was right by adding a **second implementation** of each
  pluggable dimension, plus a capacity capability:
  - **transport** — UDP (existing) and TLS;
  - **state store** — in-memory (existing) and **Redis**, the item deferred by D9;
  - **capacity harness** — a first-class load capability (D10).
- **Why Redis lands here and not in P8.** Under D3 it is a *verification output*, not a
  discovery input: the need for an external state store is already known, so building it
  early would teach nothing new. Its value is in demonstrating that the state store really
  is pluggable, which requires the abstraction to exist first. This is also where the
  "restart loses state" gap registered in P8 is finally closed.
- **Prerequisites.** A probe of sippy's TLS support — `AGENT.md` §14 forbids assuming.
  Certificates self-signed with a generation script; **no private key is ever committed**
  (`AGENT.md` §9). Redis runs as a `docker compose` service and **in-memory stays the
  default**, so `make demo`, the three test layers and CI keep running with no external
  service.

## 4. Repository and branch strategy

| Item | Branch | Repository |
| --- | --- | --- |
| P8a timer fix | `fix/sippy-retransmission-timer` | this one |
| P8 anti-fraud AS | `feat/anti-fraud-as` (already created, empty) | this one |
| P9 chained demo | `feat/chained-as-demo` | this one |
| P9.5 capacity probe | `feat/capacity-probe` | this one |
| P10 platform extraction | new branch here, output is a new repository | new repository |
| P11 TLS + harness | branches in the new repository | new repository |

`main` always stays demonstrable: `make demo` passes, CI is green, and no document describes
behaviour that is not implemented (D7).

## 5. Handover protocol for Phase 2

Each item runs in **its own conversation**, following `AGENT.md` §15:

1. Read `AGENT.md`.
2. Read `docs/README.md`.
3. Read **the section of this document for that item** (§3), plus the decisions it cites.
4. Read `docs/acceptance/criteria.md` for the acceptance items the conversation owns.

Before the conversation ends:

1. Run the definition of done (`AGENT.md` §16) and record evidence per §4.8.
2. Update **this document** — item status, what was learned, and the entry state for the
   next item. Update the `docs/roadmap.md` status line as well; it is a pointer only.
3. Update `CHANGELOG.md` and `VERSION`; commit; **do not tag** — tagging is the
   maintainer's step.
4. Write down anything a fresh conversation would otherwise re-derive.

Execution follows `AGENT.md` §14.2: the main agent plans and tracks status and delegates
implementation to a team-mode member (`mode = "acceptEdits"`); it does not implement.

## 6. Carried-forward technical constraints

Facts about sippy and this codebase that cost real effort to discover and that every Phase 2
item inherits. All were established by running the stack, not by assumption.

- **`ED2.loop()` blocks the main thread** and must stay there (`AGENT.md` §6). Never perform
  blocking work inside a sippy callback — including any state-store or list lookup on the
  call path. Existing precedent for doing this correctly: rule reload is driven from a
  loop-owned timer (`RULE_RELOAD_POLL_SECONDS`) so file I/O never blocks the stack.
- **`ED2` and `SipConf` are process-wide singletons.** A third sippy application must pin its
  own identity the way `_as_sip_identity` (call controller) and `_trunk_identity` (mock UAC)
  do, or messages will carry the wrong `Via`.
- **`SipGenericHF.getCanName()` capitalises only the first letter**, so
  `P-Charging-Vector` leaves the AS as `P-charging-vector`. Any new compact-form header must
  be probed, not assumed.
- **Port collision.** Both AS instances default to `SIP_LISTEN_PORT` 5060; running two at
  once locally requires explicit isolation.
- **Rule-file drift.** `config/routing_rules.yaml` and `config/routing_rules.compose.yaml`
  already differ only by address and are synchronised by hand. Adding a second AS turns two
  copies into four. Prefer expanding the address from the environment at load time rather
  than maintaining another copy.
- **Chained Call-IDs.** Two B2BUAs in series mean two Call-IDs; correlation across AS
  instances has to be solved, not assumed away (P9).

## 7. Open items and registered gaps

Not blocking, but each must be handled rather than discovered mid-implementation.

1. **`README.md` first sentence** still says the AS *"performs number translation and
   intelligent routing"*. It stops being true when a second use case lands, and it is the
   front door of the repository.
2. **Configuration multiplication** — see §6. Resolve in P8, not later.
3. **`CallController` two-leg assumption** must be relaxed for the UAS-only reject path (P8).
4. **Probe sippy's 608 support** before relying on it (P8 prerequisite).
5. **Probe sippy's TLS support** before P11.
6. **New gaps to register** as they are accepted: no `jCard`/`JWS` redress mechanism (D5);
   a real UAC that does not declare `sip.608` would require a media announcement (D5);
   cross-call state is in-memory and lost on restart (D9 — closed in P11 by the Redis
   store); capacity findings (P9.5).

## 8. Decisions requiring maintainer approval

One change to the rules themselves, plus one approval that an existing rule already
requires. Neither may be treated as incidental.

1. **`AGENT.md` §2 scope change.** *"No performance or capacity work … no benchmarking
   claims"* must be relaxed to permit a capacity harness while **continuing to forbid
   published benchmark figures** (D10).
2. **`AGENT.md` §14 rule 3 approval (no unconfirmed refactors).** Extracting the skeleton in
   P10 is a structural refactor, and that rule already requires an explicit, approved plan
   **before any code moves**. It is listed here so the plan is put to the maintainer
   deliberately rather than assumed.
