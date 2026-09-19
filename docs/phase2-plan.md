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

### D7 — Public throughout; a branch per work item only on demand

**Decision.** The repository stays public. Each Phase 2 item is developed **on `phase2`**, and
gets a branch of its own **only on demand** — when it needs to be discarded independently of
the rest of Phase 2, or when two items have to be worked in parallel. Where an item branch does
exist, it is cut from `phase2` and merged into `phase2` when that item's own definition of done
is met. Meeting that definition of done is **necessary but not sufficient**: the merge
additionally requires the maintainer's explicit approval in that conversation (`AGENT.md` §13),
and so does creating the branch.

*(Changed by the maintainer on 2026-09-19, superseding two earlier wordings: "each Phase 2 item
is developed on its own branch" — a per-item branch is now **on demand**, not the default — and
"merged into `main`", the target of an item merge being `phase2`. See §4, *Branch model and
documentation location*. `main` receives exactly one Phase 2 merge, the final one, and that
merge carries the approval above. Nothing else in this decision changes: `main` is still never
where unfinished work lands.)*

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

### P8a — Phase 1 defect fix: sippy retransmission-timer shutdown (landed as `v0.5.1`)

**Classification (maintainer ruling, 2026-09-18).** P8a is a **Phase 1 defect fix** — it
closes roadmap item P6 — not Phase 2 work. It is kept in this sequence only because later
items (P8, P9.5) refer to what it established. See §8 item 3 for the ruling.

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
- **Status: done, merged and released (2026-09-18)** on `fix/sippy-retransmission-timer`
  (branched from `main` at `7c4a417`), merged into `main` as `d0d0501` and released by the
  maintainer as tag **`v0.5.1`**. Acceptance item **ACC-P8A-001** with evidence in
  `docs/acceptance/report.md`. Tagging itself remains the maintainer's step (§4, `AGENT.md`
  §13).
- **Deviation from §5 (version and CHANGELOG) — history and resolution.** This handover
  protocol asks a Phase 2 conversation to "update `CHANGELOG.md` and `VERSION`"; while P8a
  was unmerged it deliberately did not, to keep the release node for the landing. The
  decision recorded at the time: `VERSION`, `pyproject.toml` and `uv.lock` remained at
  **`0.5.0`** and every P8a entry remained under the existing **`[Unreleased]`** heading —
  no dated release node opened — because nothing had been merged into `main` yet (D7: an
  item is merged only when its own definition of done is met) and `CHANGELOG.md` line 7
  states *"one version node per milestone"* (P8a is not a milestone). **Resolved
  2026-09-18:** the item landed on `main` (`d0d0501`) and the maintainer released
  **`v0.5.1`**, so the version trio now reads `0.5.1` and the P1–P7 and P8a entries that
  were under `[Unreleased]` became the `[0.5.1] - 2026-09-18` release notes. The maintainer
  also ruled that P8a is a **Phase 1 defect fix** (it closes P6), not Phase 2 work, so
  `0.5.1` is a defect-fix release and the "one version node per milestone" convention no
  longer matches a non-milestone `v0.5.1` tag; the maintainer chose to leave that
  convention text unchanged (see §8).

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
- **First steps — this item walks the §5.1 pipeline in order.** *(Renamed from
  "Prerequisites": these are P8's own stages, not a separate preliminary phase — the old
  wording invited exactly that misreading.)*
  - **1. Requirements — first, and currently absent.** P8 has **no `REQ-*` row today**:
    `REQ-F-001 … REQ-F-015` and `REQ-NF-001 … REQ-NF-010` in
    `docs/requirements/functional-and-nonfunctional.md` all belong to the Phase 1 use case.
    P8's own requirements — the verdict path, `608` rejection, cross-call state ownership,
    the second AS process — are written as new `REQ-F-*` / `REQ-NF-*` rows **before** the
    design. That they do not exist yet is the first thing to fix, not an assumption to make.
  - **2. Design.** Deltas to `docs/architecture/hld.md` and `lld.md`, plus two design-stage
    artefacts:
    - **The ADR — `0007`**, the next free number since `0001`–`0006` exist
      (`docs/architecture/adr/0007-*.md`), covering the use-case choice, the `608` rationale
      and state ownership. This is a **design artefact, not a requirement**: it records why
      the choice was made and what it accepts. The `REQ-*` rows above are what the item must
      do.
    - **A sippy probe.** Confirm that sippy emits an arbitrary 6xx through the existing
      `CCEventFail((status, phrase, None))` path — 404 and 603 are already proven, 608 is not
      — and add `Feature-Caps: *;+sip.608` to the mock UAC's INVITE. The probe belongs
      **here, in P8's design stage**, because it validates **one design assumption of this
      item only** — that the reject path can carry `608`. It is **not** a Phase-2-wide first
      step, it is not an architectural gate for Phase 2, and nothing outside P8 depends on it
      (§5.1).
  - **3–5. Implementation, tests, acceptance** follow §5.1, each with its own review gate
    (§5.2).

  **Branch history (2026-09-18 → 2026-09-19), kept as record.** **Bring the branch up to
  `main`'s tip before anything else — superseded 2026-09-19.** Under the branch model adopted
  that day, item branches are cut from `phase2` and do **not** chase `main` (§4, *Branch model
  and documentation location*); `feat/anti-fraud-as` was therefore fast-forwarded to
  **`phase2`'s tip** instead, and was deleted on 2026-09-19 — **P8 is worked on `phase2`**
  (§4 table). Done on 2026-09-18: `feat/anti-fraud-as` was fast-forwarded from `d0d0501` to
  `ebe5a17`, the release that reconciles `VERSION` and `CHANGELOG` (`0.5.1`). A branch left at
  `d0d0501` still carries `VERSION` = `0.5.0` and no `[0.5.1]` CHANGELOG node, so the first
  commit made on it would fight the release reconciliation instead of building on it — which
  is what happened on 2026-09-18 and was fixed the same day.
- **Known collisions.** The reject path is **UAS behaviour, not B2BUA**: no second leg is
  originated. `CallController` currently assumes `uaA` and `uaO` always both exist (M1
  design), so this item **changes the skeleton itself**.
- **Also.** New `AS-FRAUD-*` error codes in `src/as_app/errors.py`, following the existing
  `AS-CFG-* / AS-RULE-* / AS-ROUTE-* / AS-PEER-*` model. Port and rule-file isolation for a
  second AS (see §7). Console coverage per `AGENT.md` §16.
- **Acceptance.** P8 creates its own **`ACC-P8-*`** items in `docs/acceptance/criteria.md`.
  That file has no `ACC-P8-*` row today — only the `P8a` section (`ACC-P8A-001`) — so nothing
  is inherited and the items are P8's to add. `AGENT.md` §11 and §16 require them, each with
  evidence per §4.8, before the item is done.
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

- **Status: done (2026-09-19), worked on `phase2`; not merged into `main`, not tagged.**
  Stages 1–5 of §5.1 were completed, each with its own read-only review gate (§5.2).
  Acceptance items **ACC-P8-001 … ACC-P8-006** accepted with evidence in
  `docs/acceptance/report.md`; `VERSION` / `pyproject.toml` / `uv.lock` bumped together to
  **`0.6.0`** with the CHANGELOG node `[0.6.0] - 2026-09-19`. Merging into `main` and tagging
  remain the maintainer's steps (`AGENT.md` §13).

**What was learned (2026-09-19).**

1. **The reject assertion that matters is the absence of the second leg, not the `608`.** A
   reject that quietly relayed the call first would still answer `608` to the caller. Asserting
   that the **core side received no INVITE** — with a positive control proving the recorder
   sees the *allowed* relay in the same test — is what actually pins REQ-F-021.
2. **`Feature-Caps` selects no status code.** RFC 8688 §3.4 forwards the `608` as the final
   response whether or not `sip.608` was declared; the declaration only decides whether the
   announcement obligation was met. So the AS must not branch on it, and the unmet-obligation
   case is made **observable** (`sip_608_declared`, counter `reject.sip_608_undeclared`)
   instead of silent (ADR-0007 decision 5).
3. **sippy renders `Feature-Caps` as `Feature-caps`.** `SipGenericHF.getCanName()` capitalises
   only the first letter, so the on-wire spelling differs from the source spelling. The
   integration layer asserts the on-wire form, never the source string — the same caveat the
   LLD already records for `P-Charging-Vector`. Accepted, RFC-conformant (§7.3.1).
4. **`SIP_PHRASES[608]` is load-bearing.** sippy puts the reason phrase it is handed on the wire
   verbatim, so without the map entry the caller would read
   `SIP/2.0 608 Server Internal Error` (ADR-0007 *Verified facts*).
5. **The P8a lesson 5 scaled exactly as predicted.** The second process's timers are its own:
   `FraudAsStack.stop()` cancels its loop timers, `FraudCallMap.dispose()` cancels the per-call
   no-answer timers, and `cancel_transaction_timers()` runs **before** sippy's own
   `SipTransactionManager.shutdown()`. `test_stopping_the_process_leaves_no_timer_armed`
   asserts both the premise and the property.
6. **The `608` reject adds no retransmission population** (it originates no transaction), so
   P8 does not deepen the P8a capacity consequence — that stays P9.5's to measure.
7. **Duplication here is friction, not a design.** The internal API and the relay shell are
   mirrored, not shared; that is deliberate (ADR-0007 decision 9, no framework) and is recorded
   as a gap row that the P10 extraction inherits.

**Review gates (§5.2) — findings, and the stage in which each was fixed.** After every stage, a
read-only agent **other than the one that produced it** inspected the stage; a finding is fixed
inside its stage and the stage is not re-reviewed.

- **Stage 1 — requirements.** The gate raised reputation **decay**, the second process's own
  **stop path**, and the reconciliation of the UAS-only reject with `REQ-F-002`'s "B2BUA only";
  all three were folded into `REQ-F-016`, `REQ-F-018`, `REQ-F-021` and the SRS traceability note.
- **Stage 2 — design.** The gate asked the §5.2 design question — requirements covered, and the
  probe result actually supporting the design; the design artefacts are ADR-0007 and the
  committed `tools/anti_fraud_probe.py`, and the caveats the stage **accepted** (the
  `Feature-caps` casing, and the unmet announcement obligation for a UAC that does not declare
  `sip.608`) live in the ADR's *Verified facts* and *Gaps accepted*.
- **Stage 3 — implementation.** Findings that could not be fixed without inventing a **new,
  undesigned** behaviour were **registered, not improvised**: the unbounded retained-controller
  set (`FraudCallMap.controllers`) and the internal-API/relay-shell duplication are rows in
  `docs/production-gaps.md`.
- **Stage 4 — tests (rework done in this stage).** The gate found the coverage **over-claimed**;
  the test stage was reworked by a fresh member and the accurate positions were left visible:
  `REQ-NF-015` is satisfied by the committed **probe** plus the new **on-wire** assertion of
  `SIP/2.0 608 Rejected` (the probe is **not** a test and does **not** run in CI); `REQ-NF-012`'s
  "a restart loses it" half and `REQ-NF-013`'s "would require an announcement" half have **no
  test** — they are non-behaviours covered by the gap register; `CallScenario.expect_status` is a
  **dead Phase 1 field** (set by tests, read nowhere); the `AS-FRAUD-006` fallback and the
  unreachable `next_hop is None` branch are **untested**. All four are accepted and stated in the
  report, not hidden.
- **Stage 5 — acceptance.** Its output is the `## Phase 2 — P8 anti-fraud AS` section of
  `docs/acceptance/report.md` and the `ACC-P8-*` rows in `docs/acceptance/criteria.md`: the
  §4.8 evidence was executed from scratch by an agent that wrote none of stages 1–4, the CI
  position is recorded honestly (no run can exist for `phase2`), and the capture gap is recorded
  as **missing** rather than manufactured.

**Note for a fresh conversation — how the P8 write side was staffed (2026-09-19).** For the write
side, **one** member (`p8-designer`) produced stages 2–4 instead of a member per stage; the
maintainer flagged that. The §5.2 review gates were nevertheless performed, by **independent
read-only agents** (which also keeps the one-writing-member rule intact — see `AGENT.md` §14.1).
Stage 4's rework and stage 5 were then done by **fresh, correctly-named** members (`p8-tests`,
`p8-acceptance`). Recorded here so a fresh conversation does not have to re-derive either the
staffing deviation or the fact that the gates it did not skip were actually run.

**Entry state for P9 (set 2026-09-19).** Two B2BUA-capable AS processes now exist, each with
configurable peers and ports and both green on `phase2`, so P9 needs **no iFC emulation**:
pointing AS-1's next hop at AS-2's listen address is a `next_hops`-catalogue change (§3 P9).
Two properties P9 inherits: the anti-fraud AS relays to a **single** next hop
(`FRAUD_SBC_PEER_*`), and **two B2BUAs in series produce two Call-IDs** — the anti-fraud leg is
screened on the first Call-ID and the number-translation leg originates its own, so cross-AS
correlation is still unsolved and remains P9's known issue (§3 P9). The reject path adds no
retransmission population, so P9.5 inherits the P8a timer population unchanged.

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
- **Prerequisites.** P8a merged — **satisfied**: P6/P8a landed on `main` (`d0d0501`) and was
  released as `v0.5.1` (2026-09-18).
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
| P8a timer fix | `fix/sippy-retransmission-timer` (deleted after the merge) | this one |
| **Phase 2 integration (P8–P11)** | **`phase2`** — long-lived, created once from `main` | this one |
| **P8 anti-fraud AS** | **`phase2`** — worked directly on the integration branch | this one |
| P9 chained demo | `feat/chained-as-demo` — **on demand only**; otherwise worked on `phase2` | this one |
| P9.5 capacity probe | `feat/capacity-probe` — **on demand only**; otherwise worked on `phase2` | this one |
| P10 platform extraction | new branch off `phase2`, output is a new repository | new repository |
| P11 TLS + harness | branches in the new repository | new repository |

**Per-item branches are on demand, not the default.** An item gets a branch of its own only
when it needs to be discarded independently of the rest of Phase 2, or when two items must be
worked in parallel; otherwise the item is worked directly on `phase2`. **P8 is worked on
`phase2`.** The empty `feat/anti-fraud-as` branch was deleted by the maintainer on 2026-09-19:
under `AGENT.md` §13 every branch needs a stated purpose and an end condition, so a branch with
neither is not left sitting around.

`main` always stays demonstrable: `make demo` passes, CI is green, and no document describes
behaviour that is not implemented (D7).

### Main audit ruling — 2026-09-18

Under `AGENT.md` §13, verifying what is on `main` belongs in the closing handover. On
2026-09-18 the maintainer reviewed every commit on `main` since 2026-09-17 and confirmed that
all of them are legitimate. They fall into three groups: Phase 1 work (the P1–P7 items and
their documentation), the Phase 2 plan itself, and CI / repository hygiene. P1–P7 was Phase 1
content and therefore belongs on `main`; the Phase 2 plan is **specially authorised** because
it must carry the plans for both the second AS and the platform; the CI change is Phase 1 work.

**`b8ef30c` is within that authorisation.** The Phase 2 plan commit also touched
`docs/README.md`, `docs/roadmap.md` and `docs/specs/index.md`. Those edits are index and
navigation pointers that hang the plan into the documentation map; they introduce no
unimplemented behaviour. The maintainer explicitly approved them, so **no revert is
required** — recorded here so that a later audit does not raise them again.

**No unauthorised entry was found**, so nothing had to be taken back under the §13 approval
rule. Two accepted deltas are recorded because an audit would otherwise "discover" them:

1. **Closed 2026-09-18.** The two documentation commits `b461f80` and `d07b564` (the
   phantom-reference corrections) were committed onto `fix/sippy-retransmission-timer`
   instead of `main`, because two agents shared one working tree while that branch was
   checked out. At the time, `main` carried the four wrong `§14.3` cross-references (three
   in this document, one in `docs/roadmap.md`) and the wrong `§14.6` reference in
   `tools/README.md`. Under §13 nothing enters `main` without approval, so the corrections
   waited on the branch and reached `main` when that branch was merged (`d0d0501`); the
   maintainer accepted the delay. The corrections are now on `main`, so this ruling's
   mention of the old cross-references is the only place they appear — as history.
2. **Closed 2026-09-18.** At the time, `main` was ahead of `origin/main` by the unpushed
   rules commits (`61cab03`: the §13 approval rule and the §14.1 one-writing-agent rule).
   The maintainer then pushed them: `origin/main` and tag `v0.5.1` both point at `d0d0501`.
   Pushing remains the maintainer's step, not an agent's (§13).

### Known and accepted — maintainer rulings of 2026-09-18

Five findings were reviewed on 2026-09-18 and the maintainer ruled that each is **known and
accepted**: deliberately left as it is, not an oversight, and not to be "helpfully" corrected
by a later agent. They are recorded here, in one place, so that a future audit meets the
ruling instead of re-opening the finding. *(The paragraph above records the state **before**
the release reconciliation; item 5 below is where `v0.5.1` ends up.)*

1. **The three `## Phase 2 — P8a …` section headings stay as they are.** They are
   `docs/roadmap.md:786`, `docs/acceptance/report.md:1729` and
   `docs/acceptance/criteria.md:62`, and their wording is deliberate.
2. **The release-convention text is left unchanged.** `CHANGELOG.md:7` and
   `docs/roadmap.md:817` still read *"one version node per milestone; … tag
   `v<version>-m<n>`"*, even though the non-milestone `v0.5.1` tag now exists. The maintainer
   chose not to reword them.
3. **The generic `AGENT.md` §14 citation in P11's TLS prerequisite is left unchanged.** P11
   in §3 cites `AGENT.md` §14 without a rule number; the nit is known and deliberately not
   fixed.
4. **The remote tag `0.5.0` carries no `v` prefix** while the local tags do. Known and left
   alone.
5. **The annotated tag `v0.5.1` was moved from `d0d0501` to `ebe5a17` and created by an
   agent**, on the maintainer's explicit **one-off** exception to `AGENT.md` §13/§15 (agents
   do not create tags). **It is not a precedent.** The full record lives in the tag object
   itself (`git tag -n99 v0.5.1`); it is cross-referenced here, not repeated.

### Branch model and documentation location — maintainer ruling of 2026-09-19

**This section supersedes the ruling of 2026-09-18 that used to stand here.** That ruling
said: *"Phase 2 documentation — this plan and `docs/roadmap.md` — stays on `main`. Each
Phase 2 item's branch fast-forwards to `main`'s tip when the item starts … The maintainer
considered keeping the plan on a long-lived `phase2` branch and **rejected** it, because
`main` would then be stale for the whole of Phase 2 — exactly what D1 and D7 exist to
prevent."* The maintainer changed that decision on **2026-09-19**. The old text is quoted
here as history and replaced below as the operative rule, so that this document carries one
statement, not two contradictory ones.

**The model has three levels.**

| Level | Branch | Holds |
| --- | --- | --- |
| Global | `main` | `AGENT.md`, `docs/README.md`, `CHANGELOG.md` / `VERSION`, the M0–M4 and P1–P7 history, releases and tags |
| Phase | `phase2` | the canonical Phase 2 plan (`docs/phase2-plan.md`) and Phase 2 status |
| Item | **on demand** — for example `feat/chained-as-demo`, `feat/capacity-probe` | one item's implementation, tests and documentation; created only when the item needs to be discarded independently or worked in parallel |

- `phase2` is **long-lived**: created once, from `main`, while `main` still held the full
  plan, and merged into `main` **once**, when Phase 2 is stable, with the maintainer's
  approval per `AGENT.md` §13.
- **`main` is brought into `phase2` by merging, never by rebasing.** When `main` is merged
  into `phase2`, the conflict on `docs/phase2-plan.md` is always resolved by keeping
  `phase2`'s version: `main` holds a stub pointer, `phase2` holds the canonical plan. This
  recurs on every change to `main` during Phase 2. Merge with `--no-ff` and never rebase:
  `phase2` is published, so rewriting its history would need `--force`, which `AGENT.md` §13
  forbids without the maintainer's explicit approval.
- Item branches are cut from **`phase2`**, not from `main`, and merge into **`phase2`** when
  that item's own definition of done is met. Those merges are internal to Phase 2; they are
  **not** merges into `main`. They are **on demand, not the default**: the default is to work
  on `phase2` itself, which is what P8 does (§4 table). Creating one needs the maintainer's
  approval (`AGENT.md` §13).
- **Item branches do not chase `main`.** Nothing is synced merely because `main` moved. An
  item branch moves for a reason belonging to that item, never as a reflex to upstream
  movement.
- **The plan is read *and* edited where you are.** `docs/phase2-plan.md` is in the working
  tree of `phase2` and of every item branch cut from it, so a Phase 2 conversation reads it
  and updates it without switching branches. That is the entire point of the model.
- **`main` keeps a pointer, not a copy.** On `main`, `docs/phase2-plan.md` is a short stub
  naming the `phase2` branch as the home of the plan and stating that the plan is edited
  there, not here; `docs/roadmap.md`, `docs/README.md` and `AGENT.md` name `phase2` the same
  way. There is exactly one full text of this plan in the repository at any time — the
  reason is the *Single source of truth* paragraph in §1.

**What changed since 2026-09-18.** The old objection — that a plan on a side branch leaves
`main` stale for the whole of Phase 2 — is answered, not waved away. `main` is not silent:
it carries the stub and the pointers above, so a reviewer who arrives on `main` is told where
Phase 2 lives. What would actually violate D1 and D7 is unfinished *implementation* on
`main`, and this model keeps that off `main` exactly as the old one did; a plan on a branch
never violated either (D7's last paragraph).

**Why the alternatives were rejected** — recorded so the question is not re-litigated:

1. **"Always sync item branches with `main`."** Rejected: the rule is *event-triggered*, so
   whether an item branch is up to date depends on someone noticing that `main` moved, and it
   is *drift-prone*, because every sync is a merge with its own conflicts. P8's *First steps*
   in §3 already records one drift caused by exactly this: a branch left at `d0d0501`
   carried `VERSION` = `0.5.0` and no `[0.5.1]` CHANGELOG node, so its first commit fought
   the release reconciliation instead of building on it.
2. **"Keep the plan on `main` and read it from wherever you are with
   `git show main:docs/phase2-plan.md`."** Rejected: it solves reading and not writing —
   updating the plan still requires switching back to `main`, and the plan is edited at every
   Phase 2 handover, so this puts the dangerous operation on the most frequent path. Branch
   switching caused **two working-tree incidents in this repository on 2026-09-18** (agents
   sharing one working tree committed onto the branch that happened to be checked out; see
   accepted delta 1 under *Main audit ruling* above).
3. **"A separate long-lived branch per phase."** **This is the option adopted**, not one that
   was set aside — `phase2` is its first instance. It is listed here only so that a reader
   does not mistake it for a rejected alternative.

## 5. Handover protocol for Phase 2

Each item runs in **its own conversation, on `phase2` or on a branch cut from it when one is
needed** (§4: per-item branches are on demand), following `AGENT.md` §15:

1. Read `AGENT.md`.
2. Read `docs/README.md`.
3. Read **the section of this document for that item** (§3), plus the decisions it cites —
   **on the `phase2` branch**, where this document is in the working tree (see §5.3).
4. Read `docs/acceptance/criteria.md` for the acceptance items the conversation owns.

### 5.1 The per-item pipeline — the Phase 1 chain, item by item

Phase 1 walked a fixed chain — requirement (`REQ-*`) → design (HLD/LLD, ADR, interface
specification and message samples) → implementation → acceptance → evidence (`AGENT.md` §13,
§4.2, §11) — and §13 states that chain as a rule for any behaviour change. A Phase 2 item
walks the **same chain**, one stage at a time, each stage producing a named artefact the next
stage consumes. An item does not begin with its implementation; it begins with its
requirements.

| # | Stage | Output for this item |
| --- | --- | --- |
| 1 | **Requirements** | new `REQ-F-*` / `REQ-NF-*` rows in `docs/requirements/functional-and-nonfunctional.md` |
| 2 | **Design** | deltas to `docs/architecture/hld.md` and `lld.md`, **the ADR** for the item (`0007` for P8), and **any probe** needed to validate a design assumption |
| 3 | **Implementation** | the code |
| 4 | **Tests** | the three layers (`AGENT.md` §11) |
| 5 | **Acceptance** | `ACC-*` rows in `docs/acceptance/criteria.md` and evidence per `AGENT.md` §4.8 in `docs/acceptance/report.md` |

Each stage is owned by the item's conversation and produces its artefact **before** the next
stage begins. The list is not a checklist assembled at the end: the requirement exists before
the design that answers it, the design before the code that follows it, and the tests before
the acceptance claim that cites them.

**The probe belongs to the design stage of the item that needs it.** A probe is a design
instrument: it is written to settle **one** design assumption, and it is run and recorded
inside the **design** stage of the item whose assumption it is. It is **not a Phase-2-wide
first step** and **not an architectural gate for Phase 2**. P8's 608 probe — confirming that
sippy can emit an arbitrary 6xx through `CCEventFail((status, phrase, None))` — is P8's own
design evidence for P8's rejection semantics: it informs nothing in P9, P9.5, P10 or P11, and
no other item waits on it (see the P8 entry in §3).

**The ADR is design, not a requirement.** A requirement is a `REQ-*` row: what the system
must do, and how it is verified. The ADR is a **design-stage artefact** that records why a
choice was made and what it accepts. Phase 1 already separates the two and Phase 2 must
match — P8's `0007` is the design answer to P8's requirements, not a requirement itself.

The requirement → design → implementation chain is `AGENT.md` §13's existing rule; Phase 2 was
simply not restating it. The earlier wording of this section — an opening ritual and a closing
ritual with nothing between — read as if the chain did not apply here. This pipeline is that
rule restated for Phase 2, not a new one.

### 5.2 Review gates — one independent, read-only review per stage

After **each** stage in §5.1, **another agent reviews that stage's output before the next
stage starts.** The reviewer is a **separate agent from the one that produced the stage**, and
it is a **read-only** reviewer: it inspects and reports, it does not edit. Read-only review
also keeps the "one writing member per working tree" rule intact (`AGENT.md` §14.1) — the
reviewer never competes with the writer for the working tree.

Each review checks its stage against a fixed question:

| Stage reviewed | The reviewer checks |
| --- | --- |
| Requirements | completeness, testability, consistency with decisions D1–D10 |
| Design | the requirements are covered, the ADR's reasoning holds, the probe result actually supports the design |
| Implementation | matches the design, stays in scope, no shortcuts taken silently |
| Tests | the tests genuinely fail without the change, coverage matches the requirements |
| Acceptance | the §4.8 evidence is real, reproducible and complete |

**One review per stage, no loop.** A review that finds problems has them **fixed inside that
stage and recorded there**; the stage is **not** re-reviewed unless the maintainer asks. The
gate is a review, not a rework cycle.

**Findings are reported to the maintainer, not silently absorbed.** The reviewer reports its
findings to the maintainer. A finding that cannot be fixed without a decision — a scope
question, or a protocol or security call (`AGENT.md` §14 rule 2) — is **escalated**, not
resolved quietly inside the item's conversation.

### 5.3 Branch and reading conventions

**A Phase 2 conversation reads this plan on the `phase2` branch.** Step 3 above — and step 2
of the closing list in §5.4, which updates this document — read and edit
`docs/phase2-plan.md` in the working tree of `phase2`, or of an item branch cut from it. No
branch switch is involved; that is the point of the model (§4, *Branch model and documentation
location*). P8 has **no branch of its own** — it is worked directly on `phase2`;
`feat/anti-fraud-as` was deleted by the maintainer on 2026-09-19 (§4 table).

### 5.4 Closing the conversation

Before the conversation ends:

1. Run the definition of done (`AGENT.md` §16) and record evidence per §4.8.
2. Update **this document** (on the branch you are on — that is the canonical copy) — item
   status, what was learned, and the entry state for the next item. Update the
   `docs/roadmap.md` status line as well; it is a pointer only.
3. Update `CHANGELOG.md` and `VERSION`; commit; **do not tag** — tagging is the
   maintainer's step.
4. Write down anything a fresh conversation would otherwise re-derive.

**Known and deferred — version and CHANGELOG at item close.** Step 3 asks a Phase 2 item to
bump `VERSION` and open a CHANGELOG node at its own close, which sits awkwardly with the
release convention of one version node per milestone (`AGENT.md` §4.7) and with the per-item
branch model of §4 — an item that has not been merged anywhere is not a release. The
maintainer reviewed this on 2026-09-19 and **deferred** it: the tension is known, the wording
is left as it is for now, and it is **not** to be "helpfully" corrected by a later agent. It is
recorded here only so that a future conversation meets the ruling instead of re-deriving the
question.

**How it was actually handled at the P8 close (2026-09-19).** With that wording left unchanged,
P8 was closed by following step 3 as it reads: `VERSION`, `pyproject.toml` and `uv.lock` were
bumped together to **`0.6.0`** — the bump for a new capability, the Phase 1 precedent being
`0.5.0` for M4 and `0.5.1` for the defect-fix P8a — and a dated **`[0.6.0] - 2026-09-19`**
CHANGELOG node was opened at the item's own close, on `phase2`. The tension with "one version
node per milestone" is real and still deferred: P8 is not a milestone, and the node exists
because §5.4 step 3 asks for it.

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
4. **A design-stage probe for P8: sippy's 608 support.** It validates P8's rejection
   semantics only — not a prerequisite, and not a gate for anything else (§5.1).
5. **Probe sippy's TLS support** before P11.
6. **New gaps to register** as they are accepted: no `jCard`/`JWS` redress mechanism (D5);
   a real UAC that does not declare `sip.608` would require a media announcement (D5);
   cross-call state is in-memory and lost on restart (D9 — closed in P11 by the Redis
   store); capacity findings (P9.5).
7. **Test-harness port allocation — registered by P8a (2026-09-18), not fixed.**
   `_free_udp_port()` in `tests/integration/test_signalling_path.py` allocates the internal
   API's **TCP** port by probing **UDP**, which guarantees nothing about TCP; a poll of
   `/healthz` then hit a non-HTTP listener and failed with
   `http.client.BadStatusLine: GET /healthz HTTP/1.1` (1 failure in 42 integration runs,
   20/20 green in isolation, 0 `TypeError` tracebacks in the same 42 runs, so it is not the
   timer defect it was found beside). Row in `docs/production-gaps.md`. **Follow-up item,
   not part of P8a** (`AGENT.md` §14 rule 4): probe with `SOCK_STREAM` for a TCP port, or
   let the server bind port `0` and report the port it received. Whoever picks it up should
   also make the health poll distinguish "not up yet" from "something else is listening" —
   P9.5 will run far more processes in one host and will meet this much more often.

## 8. Decisions requiring maintainer approval

One change to the rules themselves, one approval that an existing rule already requires, and
one re-classification resolved by ruling. None may be treated as incidental.

1. **`AGENT.md` §2 scope change.** *"No performance or capacity work … no benchmarking
   claims"* must be relaxed to permit a capacity harness while **continuing to forbid
   published benchmark figures** (D10).
2. **`AGENT.md` §14 rule 3 approval (no unconfirmed refactors).** Extracting the skeleton in
   P10 is a structural refactor, and that rule already requires an explicit, approved plan
   **before any code moves**. It is listed here so the plan is put to the maintainer
   deliberately rather than assumed.
3. **P6 → P8a promotion — never separately approved; resolved by ruling (2026-09-18).**
   P8a began as roadmap item P6, parked as *Optional/Pending*; no approved decision ever
   recorded its promotion to the Phase 2 work sequence or its framing here as a Phase 2
   "(blocker)". On 2026-09-18 the maintainer ruled that **P8a is a Phase 1 defect fix that
   closes P6**, not Phase 2 work. It was fixed on `fix/sippy-retransmission-timer`, merged
   into `main` (`d0d0501`) and released as **`v0.5.1`**. Recorded here so a future audit sees
   the re-classification was resolved by ruling, not left by omission.
