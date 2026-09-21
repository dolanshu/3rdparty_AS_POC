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
  correlation is a real problem, not a cosmetic one. *(This was false of the code when P9
  started — both AS instances reused the inbound `Call-ID` on their outbound leg, which the
  maintainer ruled a **Phase 1 defect**. The number-translation instance was fixed on `main`
  and merged back; the **anti-fraud instance still carries the defect and is fixed as part of
  P9's implementation stage**. See the record below.)*

**P9 was paused on a Phase 1 `Call-ID` defect in the second leg; the pause is lifted
(maintainer ruling, 2026-09-19).** This subsection records the defect, the fix that closed
it, and the findings the fix left behind. It is kept as history rather than deleted: a
reader arriving at "P9 resumed" needs to know what was measured on the defective code and
what changed.

**Classification.** This is a **Phase 1 defect** — the code contradicts its own design
document — **not** a P9 design fact and **not** an accepted deviation. It is recorded in
P9's entry only because P9's probe is what measured it, in the same way P8a sits in this
sequence as a Phase 1 defect fix that later items refer to.

**The defect.** The Phase 1 AS is a B2BUA with two legs (`uaA` trunk, `uaO` next hop) and it
**reuses the inbound `Call-ID` on its outbound leg**, so both legs carry one `Call-ID`.
`docs/architecture/lld.md` §2.3 states the design intent — *"`To`, `Call-ID` and `CSeq`
belong to the dialog and the second leg has its own"* — and `From` / `To` / `CSeq` really are
rebuilt (new tag, fresh `CSeq`); `Call-ID` is not. `src/as_app/call_controller.py` rebuilds
the outbound `CCEventTry` with `original[0]` — the inbound `Call-ID`, unchanged — and
`src/anti_fraud_as/call_controller.py` has the same problem at
`CCEventTry(event.getData())`. sippy only generates a `Call-ID` when none is supplied
(`sippy/UacStateIdle.py:57-60`), and sippy's own B2BUA always changes it for the second leg
(`sippy/b2bua.py:346-349`, the `-b2b_N` suffix by default).

**Measurement and evidence — the finding is measured, not argued.**

- `docs/acceptance/report.md` already records the property: the captured INVITE pair is
  described as *"same Call-ID, same pass-through headers"* in the M1 and M2 capture sections
  that `ACC-M1-002` and `ACC-M2-005` cite, and `ACC-M1-005`'s evidence reads *"same Call-ID
  on both legs of the capture"*.
- `docs/roadmap.md:641` records it in the M4 acceptance narrative — *"…exchange on both legs
  with the same Call-ID"*.
- P9's own probe (`tools/chained_as_probe.py`, committed as `d6b4ece`) measured
  **`distinct Call-IDs: 1`** across a two-B2BUA chain.

**Decisions taken (maintainer, 2026-09-19).**

1. The fix is a **separate item in a separate conversation**, landed on **`main`** and then
   **merged back into `phase2`**. It is not P9's work and not Phase 2 work.
2. **P9 pauses** until that fix has landed and been merged back. No P9 implementation work
   starts before then.
3. P9's **design stage (stage 2, §5.1) must be redone** after the fix, because its artefacts
   — ADR-0008, `docs/architecture/hld.md` §9 and `docs/architecture/lld.md` §10 — were
   written against the defective behaviour. The **stage-2 review gate (§5.2) is therefore
   deferred, not skipped**: it runs against the redone design.
4. P9's **stage-1 requirements (`REQ-F-025 … REQ-F-028`, `REQ-NF-016 … REQ-NF-018`) are
   correct as written** once the fix lands: they describe the intended behaviour. **They are
   not changed**, and the plan's §6 bullet and the P9 *Known issue* above become true again.
   ADR-0008 decision 3 and the "Corrected `Call-ID` premise" rows of `lld.md` §10.5, which
   assign a rewording of `REQ-NF-016` / `REQ-F-028` and of this plan to the implementation
   commit, are **withdrawn** by this ruling.

**How the fix landed (2026-09-19).** The fix was carried out in its own conversation, on its
own branch, exactly as decision 1 requires. `main` now carries
`f1b4186` (`fix(m1): land the second-leg Call-ID fix on main`, on top of the fix commit
`d8dad31`) and `d8cabad` (the removal of the then-unused
`SipMessageRecorder.messages_for`); both were merged into `phase2` as `76a95da` and
`1676b6d`, and the one phase2-only call site left behind by the removal was adapted in
`d26d5c4`. The mechanism is a single source of truth in
`src/as_app/sip_adapter.py` — `B2BUA_CALL_ID_SUFFIX` / `outbound_call_id()` — and
`docs/architecture/lld.md` §2.3 now states it. **Nothing was pushed and no tag was created**
(`AGENT.md` §13, §15); the phase2 CI evidence is still a maintainer step, because
`.github/workflows/ci.yml` triggers on `main` only.

**What the fix left behind — three findings that are P9's, not the fix's (maintainer ruling,
2026-09-19).** The fix could not reach them: two are phase2-only artefacts and one is a
consequence of the fix that only the chain makes observable.

- **(A) The anti-fraud AS still has the defect.** `src/anti_fraud_as/call_controller.py`
  builds its outbound `CCEventTry` as `CCEventTry(event.getData())`, so event element `[0]`
  — the trunk `Call-ID` — is still reused. The file exists only on `phase2`, so the Phase 1
  fix could not touch it, and it is not a P8 regression: it has been there since P8 landed.
  It is **in P9's scope**, for two reasons: the chain is where a preserved `Call-ID` becomes
  observable (`REQ-NF-016`), and the requirement is written as satisfied only when both
  instance regenerate. **It is recorded here as a P9 stage-2 finding and fixed in P9's
  stage 3** (the implementation stage), following §5.1 rather than being patched in passing.
  **It was fixed there** — commit `8d04326`; see the stage-3 record below.
- **(B) The phase2-only adaptation `d26d5c4` is kept.** It changes two calls in
  `tests/integration/test_fraud_screening_path.py` from `messages_for(call_id)` to
  `messages_for_any((call_id, outbound_call_id(call_id)))`. That looks premature today —
  the anti-fraud AS reuses the trunk `Call-ID`, so both lookups return the same set — but it
  becomes **necessary** the moment finding (A) is fixed, and it is the correct formulation
  under (A). It is a phase2-only test file adapted to a `main`-side removal; keeping it is
  the ruling, and its justification is this bullet rather than the commit message.
- **(C) A phase2 integration flake is registered.** While the fix ran its gates, the phase2
  integration suite failed once in roughly six runs with
  `AssertionError: ... status=500` in
  `tests/integration/test_fraud_screening_path.py::test_a_broken_edit_keeps_the_previous_screening_data`,
  alongside `anti_fraud_as.call_controller: next hop did not answer in time` and
  `WARNING anti_fraud_as.call_controller`. The two merges' diff contained **zero bytes** of
  `src/anti_fraud_as/**`, so it is not a symptom of the fix; the test is green in isolation
  and the failure is a **timing flake** around the 3-second no-answer timeout of the relayed
  leg. Following the §7 item 7 precedent (register, do not improvise a fix — `AGENT.md` §14
  rule 4), it is registered in `docs/production-gaps.md` and listed as §7 item 9 below. It
  is **not** new POC friction the fix introduced, and the fix's own conversation was right
  not to register it there.

**Stage-2 review gate — run, with one blocking finding, fixed and recorded here (§5.2).** The
deferred read-only review of the redone design ran against commit `381f741`. One finding was
**blocking** and is worth recording because it is the kind of error the pipeline exists to
catch: ADR-0008 decision 4 asserted that the mock emits **no** `P-Charging-Vector` and that
the POC therefore has **no** end-to-end correlation key at all. That was **false** — the mock
has always written one (`MockUac._isc_headers`), `p-charging-vector` is in
`PASSTHROUGH_HEADERS`, and the probe now **measures** the same ICID at the trunk, at AS-2 and
at the core. It was wrong because it was reasoned from the design instead of observed, which
is precisely what `AGENT.md` §6 forbids. **Fixed inside the stage, not carried forward**: the
probe gained an ICID observation and an assertion, and ADR-0008 decision 4, the *Gaps
accepted* row, HLD §9.3, LLD §10.2 and LLD §10.5 now state the measured position — the key is
on the wire and preserved, but it is a **per-scenario literal** that **no observability
surface is keyed on**, so the *traces* still do not correlate. Per §5.2 the stage is **not
re-reviewed**; the remaining findings were non-blocking and are folded in above.

**Stage-3 review gate — run, clean, three non-blocking findings fixed inside the stage
(§5.2).** The read-only review of the implementation ran against the commit set
`8d04326`…`753a528`. **No blocking finding.** It confirmed the fix is correct and
isomorphic to `src/as_app/call_controller.py`'s derivation (all five other elements of
`event.getData()` preserved, the called number included; `self.call_id` still the trunk
value; the inbound object unmutated), that the two adapted call sites are correct under the
new design, that every `lld.md` §10.4 bullet is met by `tools/demo_chained_call.py`, that
every §10.5 row is satisfied, and that nothing outside the authorised scope was touched
(`git diff --name-only` over the range, plus an empty `git status` after a demo run). It
reproduced the acceptance signal itself: the probe's `distinct Call-IDs: 3` / `Call-ID per
leg: True` / `ICID preserved: True` at exit 0, the demo at exit 0, and all four gates green.

Three non-blocking findings were **fixed inside the stage** (commit `7b0874a`, so the stage
is **not** re-reviewed):

- **A tautological assertion.** One added assertion compared `outbound_call_id(x) != x`,
  which is true by construction because the helper always appends a non-empty `-b2b_1`, so
  it guarded nothing. It now compares the **observed** far-side `Call-ID`
  (`received_call_ids[0]`) against the trunk value, which is what §10.2 actually requires.
- **A second tautology claim was checked and rejected.** The reviewer read the *other* `!=`
  assertion the same way; the value there is already read off
  `mock.uas.received_invites[0].call_id`, so it observes the far side and was left as it is.
  Recorded because a review finding is verified before it is applied, not applied because it
  was reported.
- **The "unit/integration assertion" of §10.5 had only integration and e2e coverage.** The
  unit layer pinned no contract for `outbound_call_id` at all, so a controller reusing the
  trunk value was caught only by a socket test. `tests/unit/test_sip_adapter.py` gained one
  pure contract test (the derived value follows the documented `-b2b_1` form and differs
  from its input); `make unit` went from 199 to 200 and nothing else changed. The module
  docstring of `src/anti_fraud_as/call_controller.py`, which still read "relays the INVITE
  unchanged" and had the same looseness the method docstring was already corrected for, was
  tightened in the same commit.

**Entry state for resuming P9.** `main` carries the `Call-ID` fix and `phase2` carries it by
merge; the requirements of decision 4 are unchanged, so `REQ-NF-016` / `REQ-F-028` and this
plan's §6 and §3 wording are **not touched**; stage 2 is redone on the fixed behaviour — the
probe re-run, ADR-0008 reworked, HLD §9 and LLD §10 reworked, and the two artefacts that the
merge left self-contradictory (LLD §2.3, and the "pending rework" banners in ADR-0008, HLD
§9, LLD §10.2 and §10.5) restored to **one coherent statement of the fixed intent** rather
than left pending. Its read-only review gate (§5.2) runs then, and stages 3–5 follow. The
stored measurements are kept, because they are true observations of the code as it stood;
stage 2 re-run records the new ones beside them.

**State after stage 3.** Stages 1–3 are complete and their review gates have run: stage 1
(`REQ-F-025…028`, `REQ-NF-016…018`, written in P8's conversation and unchanged by this
ruling), stage 2 as reworked above, and stage 3 as recorded above. The implementation landed
as `8d04326` (the anti-fraud outbound `Call-ID`, the defect fix of finding (A)), `54a7582`
(the `tools/demo_chained_call.py` demo, the `make demo-chained` target and the §10.5
structural updates) and `753a528` (the README transcript brought in line with an executed
run), with the stage-3 review findings fixed in `7b0874a`. **The acceptance signal for the
fix is real and reproduced by two independent agents**: `tools/chained_as_probe.py` reports
`distinct Call-IDs: 3`, `Call-ID per leg: True`, `ICID preserved: True` and exits 0, where it
reported `distinct Call-IDs: 2` / `Call-ID per leg: False` before the fix. Finding (B) is
confirmed necessary: the two-element lookup `d26d5c4` introduced is what lets the integration
suite follow both legs now that they really do differ. Finding (C), the timing flake, is
still registered and not fixed. **Stage 4 (the three test layers) is next**; the acceptance
items `ACC-P9-001…005` and their §4.8 evidence are stage 5 and do not exist yet.

**Stage-4 review gate — run, clean, four non-blocking findings recorded (§5.2).** The
read-only review of the tests ran against commit `a14acf4`, asked the §5.2 *Tests* question
("the tests genuinely fail without the change, coverage matches the requirements"). **No
blocking finding.** The reviewer reproduced the red signal in its own way rather than
accepting the producer's word for it: a pytest plugin kept **outside** the repository
replaced only the controller's module-level `outbound_call_id` reference with the identity
— the pre-fix reuse, without touching the working tree — and the guards went red at exactly
the two points the producer recorded (`tests/integration/test_chained_topology.py:189`,
`tests/e2e/test_chained_call_flows.py:162`) **while the traversal test stayed green**, which
is what shows the per-leg assertions guard the requirement rather than something incidental.
Coverage was checked row by row: REQ-F-025 (integration and e2e, far-end evidence), REQ-F-026
(structural unit test), REQ-F-027 (delta absences at AS-2 and the core plus the literal
`SIP/2.0 608 Rejected` on the wire), REQ-F-028 / REQ-NF-016 (three wire `Call-ID`s, each
tracer keyed on its own trunk value and asserted **not** to be keyed on the other's), and
REQ-NF-017 (the target plus the four documents); REQ-NF-018 is correctly not a test target,
being the recorded-friction row. The fixture was confirmed to wire the chain **by
configuration only**, to give each stack its own registry and recorder, and to release AS-2
in `stop()`; scope was confirmed to be exactly the four test files
(`git diff --name-only a14acf4^ a14acf4`); the four gates were reproduced (lint clean, unit
203, integration 34, e2e 9), the known flake of §7 item 9 did **not** fire, and
`git status --short` was empty after the review.

Four non-blocking findings, **recorded and none fixed inside the stage**:

- **REQ-F-026's literal wording is broader than the invariant that can be asserted, and this
  is escalated, not settled here.** The row reads "neither AS imports the other", but
  `src/anti_fraud_as/call_controller.py` imports `as_app.sip_adapter` **by design**
  (ADR-0007 decision 9), so only the forbidden direction (`src/as_app` ↛ `anti_fraud_as`) is
  assertable and only it is asserted — the unit test says so in its docstring. Rewording a
  frozen requirement is not a call a stage review may take (§5.2), so it becomes §7 item 10
  for the maintainer. Recorded precisely because the assertion is **narrower** than the
  requirement's text: the gap is in the wording, not in the test.
- **REQ-NF-017's "no new port" is not asserted, and the no-new-knob check is a substring
  heuristic** (`.env.example` keys containing `chain`). Left as it is: pinning the whole
  declared key set would make every future knob edit this test, which is more machinery than
  the finding warrants.
- **AS-2's wire recorder is built but discarded** (`tests/conftest.py`), so REQ-F-027's
  absence is proven through `tracer.known_call_ids()` rather than through AS-2's received
  bytes. Adequate — AS-2 traces on INVITE — but it is a proxy, and it is registered as one.
- **Two assertions are implied by the ones above them** (`test_chained_topology.py:191`,
  `test_chained_call_flows.py:163`). Redundant, not vacuous: both compare observed wire values.

**Stage-5 review gate — run, clean, four non-blocking findings fixed inside the stage
(§5.2).** The read-only review of the acceptance record ran against commit `f68ed27`, asked
the §5.2 *Acceptance* question ("the §4.8 evidence is real, reproducible and complete"). **No
blocking finding.** The reviewer re-ran every command the record quotes and compared the
numbers, the exit codes and the selected test names against the claims: lint clean, unit 203,
integration 34, e2e 9, the chained integration 3, `-k reject` `2 passed, 3 deselected`, the
combined `5 passed`, the two structural unit selections, the probe at exit 0 with
`distinct Call-IDs: 3` / `Call-ID per leg: True` / `ICID preserved: True`, and the demo at
exit 0 with its five `OK` lines — all matched. It also ran the e2e file with `-s` and compared
the emitted trace **shape** (columns, event names, summaries, the `internal -` / `internal
trunk` rows, the `-b2b_1` derivation) against the quoted §2 block and found no structural
mismatch, i.e. nothing suggesting the excerpt was composed rather than captured. It confirmed
the two deliberate qualifications are accurate — ACC-P9-001 claims only the one-way import
independence, ACC-P9-004 only the substring knob check — that every item carries all four
§4.8 kinds either as evidence or as an explicit honest declaration, and that scope was exactly
`docs/acceptance/criteria.md` and `docs/acceptance/report.md`.

Four non-blocking findings were **fixed inside the stage** (commit `4d3e924`, so the stage is
**not** re-reviewed). One of them was a real defect in the record rather than prose polish:

- **The ACC-P9-005 verification command did not reproduce.** It quoted `grep -nE` with the
  alternation pipes escaped as `\|` for markdown; in `grep -E` a backslash-pipe is a literal
  `|`, so the command exited **1** with no matches while the row claimed exit 0. This is the
  kind of finding the gate exists for: a quoted command that a reviewer cannot run. Replaced
  with a pipe-free `grep -n -e … -e …` form, verified at exit 0 with five matches. The report's
  own copy of the command used unescaped pipes and did reproduce, and was left as it was.
- **A copy-pasted environment claim was false.** The P9 record read "repository `VERSION` =
  0.5.1 at the time of the run" — inherited from the P8 section above it, while `VERSION` has
  been `0.6.0` since `4d32e80`, an ancestor of every P9 commit. Corrected.
- **Two criteria rows named slightly more than their commands prove.** ACC-P9-001 carried the
  requirement's sequence including `ACK`, which **no P9 test asserts** (the mock's UAC records
  no `ACK` in the trace); the expected result now states exactly what is asserted and the gap
  is recorded under the accepted limitations. ACC-P9-004 named three of the four documents
  the test checks, omitting `tools/README.md`; corrected in both the criteria row and the
  report prose.
- **The §3 CI wording overstates.** "No CI run **can** exist for `phase2`" is wrong as written
  — `origin/phase2` exists, this branch is 21 commits ahead of it, and a pull request from
  `phase2` into `main` would run CI. The conclusion (kind 3 is not producible from this
  environment, and nothing is pushed) is correct and stands; the sentence was reworded to say
  exactly that.

**State after stage 5.** Stages 1–5 are complete and their review gates have run. The
acceptance record is `f68ed27` (the five `ACC-P9-*` rows and the four-kind evidence) with the
gate's findings fixed in `4d3e924`. P9's §4.8 position is: kinds 1, 2 and 4 are carried as
evidence (kind 4 as "partial", because the tests assert the recorded wire bytes and no sample
can be committed — `docs/specs/message-samples/` is generated and gitignored, and
`tools/capture_call.py` drives one AS, not the chain), and kind 3 is honestly declared **not
producible** because the CI workflow's `push` / `pull_request` triggers target `main` and
nothing here is pushed. **What remains is the item close of §5.4**: the SRS rows to `done`,
the chained section in `docs/demo-script.md` / `docs/demo-steps.md`, and `VERSION` /
`CHANGELOG.md` — commit, and **do not tag**.

- **Status: done (2026-09-19), worked on `phase2`; not merged into `main`, not tagged.**
  Stages 1–5 of §5.1 were completed, each with its own read-only review gate (§5.2), and the
  item close of §5.4 was then performed: the SRS rows `REQ-F-025 … REQ-F-028` and
  `REQ-NF-016 … REQ-NF-018` are `done`, `docs/demo-script.md` §5b and `docs/demo-steps.md`
  §1.6 carry the chained section, and `VERSION` / `pyproject.toml` / `uv.lock` were bumped
  together to **`0.7.0`** with the CHANGELOG node `[0.7.0] - 2026-09-19`. Acceptance items
  **ACC-P9-001 … ACC-P9-005** accepted with evidence in `docs/acceptance/report.md`. Merging
  into `main` and tagging remain the maintainer's steps (`AGENT.md` §13).

**What was learned (2026-09-19).**

1. **The `Call-ID` premise was wrong for both AS instances, and the probe is what caught it.**
   The plan recorded "two B2BUAs in series produce two different Call-IDs" as a design fact, but
   the code reused the inbound `Call-ID` on every outbound leg, so the probe measured
   `distinct Call-IDs: 1` at the start and `2` after the Phase 1 fix — never the intended `3`.
   The premise was never argued into place; it was **observed** to be false, which is exactly
   what `AGENT.md` §6 asks for. The fix is **per controller**, because each AS runs a bare
   `sippy.UA` rather than `sippy.CCB2BUA`, whose own B2BUA is the thing that would have
   regenerated the value.
2. **The ICID is preserved end to end but nothing is keyed on it, so the chain is genuinely not
   correlatable — measured, not argued.** `P-Charging-Vector` survives at the trunk, at AS-2 and
   at the core (`ICID preserved: True`), yet it is a **per-scenario literal**
   (`poc-chained-allow`) that no observability surface is keyed on, so the per-instance traces
   still cannot be joined. The stage-2 gate had to correct a design claim that asserted the mock
   emits no ICID at all — the design had reasoned past the wire.
3. **Chaining needed no new code path and no new configuration knob.** Pointing AS-1's next hop
   at AS-2's listen address is a `next_hops`-catalogue change; the demo asserts that no declared
   `.env.example` key contains `chain`. That absence is what makes the topology
   **configuration-only**, and it is what P10 inherits as its starting point.
4. **The review gates found real defects that a self-check would not have.** A tautological
   assertion (`outbound_call_id(x) != x`, true by construction); a quoted acceptance command
   (`grep -nE` with escaped `\|`) that could not run and exited `1` while the row claimed `0`;
   and a copy-pasted environment claim (`VERSION` = 0.5.1) that had been false since `0.6.0`.
   Each was fixed inside its stage, and the second is the kind of finding only an independent
   re-run produces.
5. **The demo-as-a-guard pattern is what makes `make demo-chained` evidence rather than a
   printout.** It asserts the properties — including the reject's short-circuit as an
   **absence** at AS-2 and the core — and exits non-zero on any mismatch, so the five `OK` lines
   are a verdict, not narration. That is the same shape the P8 `make demo-fraud` established.

### P9.5 — Read-only capacity probe

- **Goal.** Discover where the capacity boundary is. **Do not change the skeleton** — add a
  load generator plus observation only.
- **Prerequisites.** P8a merged — **satisfied**: P6/P8a landed on `main` (`d0d0501`) and was
  released as `v0.5.1` (2026-09-18).
- **Output.** The constraints found (concurrency ceiling, back-pressure behaviour, what
  blocks the event loop) become inputs to P10 and are registered as gaps.
- **Explicitly not:** any published calls-per-second or latency figure (D10).

**What was learned (2026-09-19).** `tools/capacity_probe.py` places concurrent calls at an
escalating offered load against the real chained topology in one interpreter and observes
what degrades first. It publishes **no** calls-per-second and no latency figure (D10); every
value it prints is a boundary statement.

1. **No completion ceiling was found inside the configured range, but the event loop is the
   serialisation point.** Every call completed at every offered level up to **64** concurrent
   calls, so the boundary is above the range and has to be escalated to. The observable
   constraint is the **loop gap**: the largest gap between two polls of the single
   process-wide `ED2` loop grew from `0.03s` at offered level 1 to `0.12s` at 64 — one
   blocking, single-threaded dispatcher serves both AS instances and the mock, so a busy loop
   delays every call's timers and responses alike. The harness runs all three stacks in one
   interpreter; in production each instance owns its own process and loop, so the number of
   instances is not what this measures.
2. **The 3-second no-answer timeout is a wall-clock boundary, not a resource limit**, and it
   is what turns a slow call into a failed one under load. Inside the configured range the
   chain neither refused nor degraded: every call up to 64 completed and no `503` was ever
   observed. What is absent is any admission control or back-pressure, so the fixed 3-second
   wall-clock timeout is the only thing that can turn a slow call into a failed one.
3. **The failover hop's no-answer timer does not fire, so `timerB` — not the application —
   ends the call.** This is the sharpest finding, and it is stronger than the P8a lesson.
   Towards an unreachable hop the controller logs `next hop did not answer in time` **once
   per call** and `trying failover hop` once, then nothing: the second hop's own 3-second
   timer never fires, the application never gives up, and the trunk is **not** released inside
   a window several times the nominal timeout (measured `0 of 4` after 9s and `0 of 4` after
   25s). The calls are ended by sippy's `timerB` = 32s reaping the client transaction.
   Registered as a gap below; the repair belongs to the failover path in
   `src/as_app/call_controller.py` (P10's material), not to a read-only probe.
4. **The armed transaction population scales with burst × hops and outlives the call's
   decision.** The shipped mobile rule lists a primary and a failover hop, so each call leaves
   one armed client transaction **per hop tried** — measured `8 of 8` armed for `timerB =
   32.0s` for a 4-call burst — and INVITEs keep being retransmitted (`timerA` doubles its
   interval, only `timerB` stops it): `36` transmissions for that burst. A burst therefore
   leaves up to `N*H` transactions and their timers in the process for ~32s whatever the
   application decided. Once `timerB` has fired the transactions are still present in
   `SipTransactionManager.tclient` (measured `8` entries, `0` with `timerB` armed), so the
   reap does not clean the table.

Running the probe with a non-default window above `timerB` (40s) triggers sippy
`AttributeError: 'NoneType' object has no attribute 'pop'` tracebacks on teardown — the same
defect class as the registered P8a gap (`docs/production-gaps.md`), on a different code path,
and not hit by the default run.

- **Status: done (2026-09-19), worked on `phase2`; not merged into `main`, not tagged.**
  The probe is `tools/capacity_probe.py`, run explicitly and **not** in the gate (no Makefile
  target, not collected by pytest); the constraints above are registered in
  `docs/production-gaps.md`. No calls-per-second and no latency figure is published (D10),
  and no file under `src/` was changed — P9.5 is read-only by definition.

**P9.5 review gate — run, clean, three non-blocking findings fixed inside the stage (§5.2).**
The read-only review of the probe ran against commit `9713c5f`, asked the §5.2
*Implementation* question ("matches the design, stays in scope, no shortcuts taken
silently") and the design question's probe clause ("the probe result actually supports the
design"). **No blocking finding.** Read-only-ness was verified independently:
`git diff --name-only 9713c5f^ 9713c5f` is exactly the four paths
(`tools/capacity_probe.py`, `tools/README.md`, `docs/production-gaps.md`,
`docs/phase2-plan.md`) with nothing under `src/`. The probe was confirmed to only generate
load and observe — it imports `AsStack` / `FraudAsStack` / `SMockApplication` and reads
public surfaces (`place_call`, `outcome_for`, `start`/`stop`, `recorder.messages`, plus
`getattr` reads of `transaction_manager.tclient` and `teB`) with no monkeypatch or mutation
of the production paths, and its only write is a rewritten rule copy into a
`tempfile.mkdtemp` directory. The deliverable was confirmed to be constraints only: the
output carries offered levels, completion counts, the loop gap (loop responsiveness, not
call latency), the `timerB` constant, the INVITE count and the `tclient` entries — **no**
calls-per-second and **no** latency figure (D10, §8 item 1). The reviewer reproduced the
probe (`uv run python tools/capacity_probe.py`, exit 0) and checked every recorded value:
the positive control `1 of 1` completed, all levels up to 64 completed (`64 of 64`), the
loop gap `0.03s` → `0.17s`, and towards the unreachable hop `0 of 4` released, `8 of 8`
armed for `timerB = 32.0s`, `36` transmissions. It then escalated the window past the
recorded 9s: at 15s `0 of 4` released / `40` transmits, at 25s `0 of 4` / `48` transmits
(confirming the "`0 of 4` after 25s" claim), and at 40s `4 of 4` released with `8` entries
still in `tclient` and `0` armed — confirming both the sharpest finding (the application
never gives up; `timerB` ends the call) and that the table is not reaped. It confirmed the
probe is **not** in the gate: no Makefile target, `pytest --collect-only` matches nothing
(`pyproject.toml` `testpaths = ["tests"]`), and it is absent from `.github/workflows/ci.yml`.
Gates: `make lint` clean (ruff format 92 files, ruff check passed, mypy 28 source files),
unit **203**, integration **34**, e2e **9**; the known flake of §7 item 9 fired once on the
first integration run and passed on re-run.

Five non-blocking points were raised. **Three were fixed inside the stage** (commit
`3c38e9e`, so the stage is **not** re-reviewed):

- **The `DEFAULT_UNREACHABLE_WINDOW_SECONDS` comment was wrong about the reap.** It said
  `timerB` reaps the client transactions; the review measured the opposite — after `timerB`
  fires the arm is gone and the entries **linger** in `tclient`, the table is not reaped.
  Fixed: the comment now says the probe measures the **armed** population.
- **A cosmetic `Nones`.** The burst-constraint line printed `timerB = Nones` on the
  no-armed-transaction path. Fixed with the same `None` → `-` fallback the interval line
  above it already uses.
- **"degrades per call" was an overstatement, and it was corrected in both places.** The gap
  row and "What was learned" point 2 both claimed the chain degrades per call, but inside the
  configured range nothing degraded: all 64 concurrent calls completed and no `503` was ever
  observed. Restated as: no completion ceiling and no refusal inside the configured range,
  and no admission control or back-pressure — the fixed 3-second wall-clock timeout is the
  only limit that can turn a slow call into a failed one. Recorded because the original claim
  was **stronger** than what was observed.

Two points were **recorded rather than fixed**:

- **A non-default window above `timerB` (40s) triggers sippy
  `AttributeError: 'NoneType' object has no attribute 'pop'` tracebacks on teardown** — the
  same defect class as the registered P8a gap (`docs/production-gaps.md`), on a different
  code path, and not hit by the default run. Recorded in the P9.5 section above.
- **A reproducibility note, left as correct behaviour.** One of six unreachable-hop runs
  spuriously reported `4 of 4` released / `0` INVITEs; the probe's own guard flagged that run
  `FAILED` (exit 1) rather than printing a false pass, so the harness discriminates honestly.
  No fix — the guard doing its job is the correct outcome.

### P10 — Platform extraction (new repository)

- **Goal.** Extract the skeleton shared by both AS instances into a library; both become its
  users; this repository becomes the reference implementation.
- **Inputs.** Three genuine drivers: pluggable state store (P8), skeleton friction (P9),
  capacity/back-pressure constraints (P9.5).
- **Constraints.** This is a structural refactor of `src/as_app/` and therefore requires an
  explicitly approved plan under `AGENT.md` §14 rule 3 (no unconfirmed refactors) — it
  must not be done incidentally. The new repository follows a library standard, not this
  repository's application standard (D8).

**P10 requirements-stage review gate — run, PASS-WITH-FINDINGS, all four findings fixed inside
the stage (§5.2).**
The read-only review of the requirements stage ran against commit `dab30f0`, asked the §5.2
*Requirements* question ("completeness, testability, consistency with decisions D1–D10") and
returned **PASS-WITH-FINDINGS — no blocker**: one major and three minor findings. The gate
verified the diff independently — `1 file changed, 39 insertions(+)`, `0` deletions — so the
note's claim that no Phase 1, P8 or P9 requirement is changed holds. It also confirmed:
`REQ-F-029`'s citation of the §14 rule 3 waiver matches §8 item 2, which is "APPROVED
2026-09-19" and does say the plan is written first and reviewed before code moves; `REQ-NF-020`
is correctly scoped to *enable* rather than *build* P11's pluggable transport, pluggable state
store and harness, so it does not contradict the still-`done` `REQ-NF-002` (UDP-only) — TLS
supersession belongs to P11 (D10); the test named in `REQ-F-030`
(`tests/unit/test_repository_baseline.py::test_as_app_does_not_import_the_anti_fraud_as`) exists
with that exact name and asserts the stated direction; and all six new rows use the `planned`
status vocabulary, with their `ACC-P10-001…006` references unique and correctly deferred to the
acceptance stage.

One major and three minor findings were raised. **All four were fixed inside the stage** (commit
`91c737d`, so the stage is **not** re-reviewed — §5.2 "one review per stage, no loop"):

- **(major) No requirement covered the new library's own test suite.** `REQ-F-031` only states
  that this repository's three layers stay green; a brand-new repository has no stated testing
  standard or gate. Fixed: `REQ-NF-021` added — the library carries its own suite and its own
  gate (`ruff` format and lint, `mypy`, `pytest`), covering the pure helpers, the sippy adapter
  boundary and the library-level independence assertion of `REQ-F-030`.
- **(minor) The requirement set was silent on whether the move is staged.** Nothing said the
  ~8000-line skeleton move is staged rather than all-or-nothing, nor what keeps the repository
  demonstrable mid-move. Fixed: `REQ-F-033` added — the skeleton moves in steps that each leave
  this repository building, linting and passing its three layers (D7, `AGENT.md` §10).
- **(minor) The traceability note carried a test count that was not established verbatim
  anywhere in the repository.** The note said "(246 tests at the time of writing)", a figure
  only derivable by summing the `203` / `34` / `9` layer counts recorded in
  `docs/acceptance/report.md`. Fixed: replaced with a pointer to where the counts are on record.
- **(minor) `REQ-F-030`'s library-independence claim had no named verification.** The row asserts
  the library imports neither `as_app` nor `anti_fraud_as`, but only the preserved one-way
  invariant had a named test. Fixed: the row was amended to cite the library's own suite
  (`REQ-NF-021`).

`ACC-P10-007` and `ACC-P10-008` are the two new acceptance references (from `REQ-F-033` and
`REQ-NF-021`), to be created in P10's acceptance stage like `ACC-P10-001…006`. No code has moved:
P10's design stage has not started, and §8 item 2 requires the plan to be written and reviewed
before any code moves.

**P10 design stage (stage 2) — the ADR and the consumption probe (2026-09-19).** The stage
produced **`docs/architecture/adr/0009-platform-library-extraction.md`** and a scratch probe of
the `uv` consumption mechanism. **No code moved:** the commit is the new ADR plus this plan
edit, with nothing under `src/` or `tests/`, so §8 item 2's "the plan is written and reviewed
before any code moves" is still the operative gate and the implementation stage has not started.
The ADR is the design answer to `REQ-F-029 … REQ-F-033` and `REQ-NF-019 … REQ-NF-021`; it does
not restate them.

The ADR settles eight decisions, in its own words:

1. **The library's identity and standard.** Repository `as_platform` (sibling `../as_platform`),
   distribution `as-platform`, import package `as_platform`; the **D8 library standard** — API
   reference, integration guide, compatibility matrix (REQ-NF-019) — not this repository's
   `AGENT.md` §4.1 application layout; `py.typed` and the pinned sippy travel with it.
2. **The module split.** `observability/`, `sip_adapter`, the `errors` mechanism, the `bootstrap`
   plumbing, the version chain, the `internal_api` shell, the controller shell (`Base*`) and the
   stack shell move; `routing/`, `screening.py`, `caller_state.py`, `screening_data.py`, the
   config and the entry points stay; `as_app.sip_adapter` and `as_app.observability.*` stay as
   thin **re-export facades** so the by-path references in `tools/`, `tests/`, the ADRs and the
   LLD keep resolving and the three layers remain the unchanged anti-regression guard. The
   `NextHop` **value object** moves too, into its own library module (`as_platform/hop.py`), with
   `as_app.routing.rules` **re-exporting** it — a third facade — because the base controller and
   `sip_adapter.build_request_uri` are typed on it and leaving it in `routing/` would make the
   library import `as_app.routing.rules`, breaking `REQ-F-030`. The catalogue that *produces* the
   hop list (`routing/rules.py`'s document, schema, `RuleSet` and `RuleSetStore`, and
   `routing/engine.py`) stays use-case-specific in this repository.
3. **The error model: one mechanism, per-family code sets, and the `REQ-F-023` delta.** Python
   forbids extending an `Enum` that has members, so the library owns a **memberless `ErrorCode`
   base** with `SIP_PHRASES`, `sip_status_for` and `AsError`; the skeleton codes
   (`AS-CFG-*`, `AS-PEER-*`, `AS-INT-*`) become `SkeletonErrorCode`, the translation codes stay
   in `src/as_app/errors.py`, and the anti-fraud gains `FraudErrorCode` in its own package.
   Every code, status and message is byte-identical (REQ-F-031), but `REQ-F-023` and `AGENT.md`
   §4.3 name a **location** (`src/as_app/errors.py`) that the split moves — a wording delta,
   escalated the way §7 item 10 was rather than reworded by a stage (§5.2). The split forces one
   **bounded test edit**, stated precisely rather than as "an import line": the permitted class
   of test change is *"repoint a read, an iteration or a type annotation of a moved enum member
   at the family enum that now owns it"*. No assertion's expected value changes; no test is
   deleted, weakened or added; the one uniqueness/status-coverage test is **strengthened** in
   scope to cover all three families. The five affected sites are enumerated in ADR-0009
   decision 3 and the implementation stage reports the complete list in its acceptance evidence.
4. **The controller seam and `PolicyDecision`.** `BaseCallController.apply_call_policy()` keeps
   the LLD's "single seam" name and calls one application hook, `decide(event) ->
   PolicyDecision`; `PolicyDecision` is plain data (`action`, `outbound_event`, `next_hops`,
   `error`, `disposition`, `attributes`, plus the reject trace/log strings `reject_trace_summary`
   / `reject_log_message` / `reject_log_fields` and the relay `relay_log_message` /
   `relay_log_fields`), so the base applies a decision without knowing either use case's
   vocabulary. The base owns the failover form of `_relay_from_next_hop`; the
   anti-fraud's one-element hop list reproduces its no-failover behaviour exactly. The one-leg
   relaxation of LLD §9.6 becomes a stated base invariant, not an anti-fraud special case.
   **The seam reproduces both reject and allow paths byte for byte:** the per-application trace
   summary and log messages travel as **data**, because branching on "which application am I" is
   forbidden; the peer-status key is an **overridable point** on the base (default
   `name:address:port`; the anti-fraud overrides to `address:port` with a `"-"` fallback, and its
   hop name `fraud_sbc_peer` is never rendered); and the base stores the serving hop as a
   `NextHop` while `uaO` still receives the `(address, port)` tuple.
5. **The two pluggable seams are interfaces only** (REQ-NF-020): `Transport` / `UdpTransport` and
   `StateStore` / `InMemoryStateStore`, one implementation each. No second transport, no external
   store, no load harness; the state-store seam sits **under** `CallerStateStore`, which stays
   process-level and out of the per-call controller (D9, LLD §9.2). The capacity harness is a
   P11 capability and is not a seam.
6. **Consumption: `[project].dependencies` plus `[tool.uv.sources] as-platform = { path =
   "../as_platform", editable = true }`.** `editable = true` is required by the staged extraction
   (a step edits the library and runs this gate against it). Four measured properties shape it,
   below.
7. **The staged extraction: seven steps, each leaving `make lint` clean and all three layers
   green** (REQ-F-033, D7, `AGENT.md` §10) — (1) create the library and add the path dependency,
   no code moves; (2) move the leaf modules with the facades; (3) move the version chain and
   bootstrap plumbing; (4) move the controller shell and rewire both controllers to `decide()`;
   (5) move and generalise `internal_api`; (6) add the two seams; (7) give the library its own
   suite, gate, independence assertion and documents. The order is by dependency; step 4 is the
   only step that can change behaviour and is guarded by the three layers plus
   `tools/chained_as_probe.py`.
8. **`AGENT.md` §10 is restated, not weakened:** "clone **both** repositories side by side →
   `uv sync` → `make demo`", recorded as an explicit exception (REQ-F-032); the library carries
   its **own** gate (REQ-NF-021), which does not replace this repository's three layers.

**The consumption probe (design instrument, run and recorded in this stage).** A scratch probe
under `/tmp/p10probe` — a throwaway `as_platform` (`VERSION` 0.4.0) and seven consumer variants
(six top-level, one nested), each varying one `pyproject.toml` key — settled the mechanism of
ADR-0009 decision 6. The scratch form is not committed, but its **reproducible form is
`tools/path_dependency_probe.py`** (registered in `tools/README.md`), which rebuilds the layout
in a temporary directory, re-measures every fact and exits non-zero when any expectation does
not hold — the `tools/capacity_probe.py` (P9.5) guard is the precedent. Tool versions
`uv 0.12.15`, CPython `3.10.12`. Four facts are **not** what a reader would assume, and each is
now a stated property of the decision rather than a surprise in the implementation stage:

- **The source is mandatory.** A dependency key alone does not resolve — `uv sync` fails with
  *"Because as-platform was not found in the package registry … your project's requirements are
  unsatisfiable"*.
- **The default is a copy, not a link.** A `path` source with no `editable` key installs a
  non-editable copy (`direct_url.json` → `{"dir_info":{"editable":false}}`); `editable = false`
  is the explicit spelling of the same thing; only `editable = true` produces the
  `_editable_impl_as_platform.pth` link.
- **The version pin is ignored.** `dependencies = ["as-platform>=99.0"]` with a `path` source
  installed the checkout's `0.4.0` and exited `0`, so the pin is not a guard.
- **The lock is not a version guard either.** With the library bumped `0.4.0` → `0.5.0`,
  `uv sync --locked` refused (*"The lockfile at `uv.lock` needs to be updated, but `--locked`
  was provided"*) while `uv sync --frozen` accepted the skew, installed `0.5.0` silently and
  left the lock recording `0.4.0`. A `path` dependency has no version to resolve against, so
  neither the pin nor the lock constrains the library; what catches a skew is a **gate** — the
  library's own gate plus this repository's gates against the sibling checkout — and CI's
  `uv sync --frozen` lock comment is true for **registry** dependencies and **not** for this
  path dependency, so **every CI job needs a second checkout** of the library repository.

`py.typed` is a hard requirement of the same gate: without it `mypy` reports `Skipping analyzing
"as_platform": … missing library stubs or py.typed marker [import-untyped]` and `make lint`
fails. The `path` is resolved relative to the consuming `pyproject.toml`, so `../as_platform`
means a sibling of this repository's root and a deeper nesting does not find it — which is what
makes REQ-F-032's "side by side" exact.

**Obligations this design places on the implementation commit** (all stated in ADR-0009, none
performed here): `AGENT.md` §10 (the restated clean-checkout sentence) and §4.3 (the error model's
location — **§4.3 is updated in the implementation commit**, because it is a structural document
and `AGENT.md` §13 requires structural changes to update it), `README.md` and `docs/README.md` (the second
checkout and the **ADR index range**, which both read "ADR-0001 … ADR-0008" today), the
`docs/production-gaps.md` rows the ADR's *Gaps accepted* lists (no versioned consumption; the
interface induced from two instances; no second transport / store / harness; no mock or console
in the library; the naming debt; the library gate not in this repository's CI; the `REQ-F-023`
location delta; the probe's stand-in scope), and `ACC-P10-*` in the acceptance stage.

**Unsettled at the time of this record, and recorded rather than hidden.**

- **The HLD/LLD deltas that §5.1 also assigns to the design stage are not written.** The ADR
  states what they must contain (a new LLD section naming the library boundary; the HLD deployment
  view showing two repositories), but neither file is edited in this stage. They are the next
  artefact before any code moves; the reason they are small is that the extraction changes no
  observable behaviour (REQ-F-031) and LLD §9.1 already states the shared/use-case-specific
  boundary.
- **The error-model split forces one bounded test edit** (ADR-0009 decision 3). The permitted
  class of test change is *"repoint a read, an iteration or a type annotation of a moved enum
  member at the family enum that now owns it"*. No assertion's expected value changes; no test
  is deleted, weakened or added; the one uniqueness/status-coverage test is **strengthened** in
  scope to cover all three families. The five affected sites are enumerated in ADR-0009
  decision 3. This is the one place where the traceability note's literal *"If that suite has to
  change to accommodate the extraction, the extraction is wrong, not the tests"* meets the
  split; the note is **qualified in place** so it keeps its force — the extraction may not
  change what a test asserts — while naming this bounded exception.
- **`REQ-F-023` and `AGENT.md` §4.3 name a location the split moves**, and a stage may not reword
  a frozen requirement (§5.2). Escalated to the maintainer, like §7 item 10.

**P10 design stage (stage 2) — the HLD/LLD deltas and the three rulings (2026-09-19).** The
stage's design artefact is completed by the two deltas §5.1 also assigns to it: a new
**`## 10. The platform library (P10)`** in `docs/architecture/hld.md` and a new
**`## 11. The platform library (P10)`** in `docs/architecture/lld.md`. Both mirror the P8/P9
section shape and cite ADR-0009 rather than re-arguing it: the HLD section states the library is
a build-time dependency (no new process, port or listener), the two-repository checkout
(REQ-F-032) and that nothing observable moves (REQ-F-031); the LLD section gives the module
split and its inverse, the `PolicyDecision` seam, the error families, the two seams, the
consumption mechanism and the seven-step order (11.1–11.7). Nothing under `src/` or `tests/` is
touched, so §8 item 2's "the plan is written and reviewed before any code moves" is still the
operative gate and the implementation stage has not started.

The three points the ADR had escalated to the maintainer were **ruled on, and the rulings are
recorded in the ADR** (each with its reasoning kept visible), and the SRS traceability note
carries the `REQ-F-023` delta:

- **`REQ-F-023` is not reworded.** The row's text was true when written and a stage may not
  reword a frozen requirement (§5.2); the delta goes in the SRS **traceability note**, the
  repository's established precedent (P8a records the `REQ-F-011` delta the same way).
  `AGENT.md` §4.3 is a structural document, not a frozen requirement, so `AGENT.md` §13 requires
  it to be updated **in the implementation commit** to name the library mechanism and the three
  families.
- **The bounded test edit is accepted and recorded, stated precisely.** The permitted class of
  test change is *"repoint a read, an iteration or a type annotation of a moved enum member at
  the family enum that now owns it"*; no assertion's expected value changes, and the one
  uniqueness/status-coverage test is **strengthened** in scope to cover all three families.
  `REQ-F-031` promises the three layers **stay green**, not that no test file's read, iteration
  or annotation ever changes — this is the only class of test change the extraction is allowed
  to make, and the five sites are enumerated in ADR-0009 decision 3.
- **`TrunkMessage` is deleted with the move, not carried into the library.** It is provably dead
  (two references, both inside its own module: `src/as_app/sip_adapter.py:41` and `:122`), and
  carrying known-dead code into a brand-new artefact is the wrong default; the deletion is
  behaviour-neutral and is performed as part of the move, with its `__all__` entry. LLD §9.1's
  friction note now records that P10 removed it rather than inherited it.

**P10 design stage (stage 2) — the design-stage review gate and its findings (2026-09-19).** The
gate §5.2 requires ran against `dc1ab18` and returned **FAIL: one blocker, three major and four
minor findings**. Per §5.2 the findings are fixed **inside the stage** and the stage is **not
re-reviewed**. All eight are closed in this commit; **no code moved** — nothing under `src/` or
`tests/` changes, and the only added file is the design instrument `tools/path_dependency_probe.py`
(§8 item 2's "no code moves before the plan is reviewed" still holds, and the implementation stage
has not started). Each finding, and the one-line fix:

- **Finding 1 [blocker] — `NextHop` had no home, so the library would have imported `as_app.routing.rules`, breaking `REQ-F-030`.** `NextHop` now moves into the library in its own module (`as_platform/hop.py`) and `src/as_app/routing/rules.py` **re-exports** it (a third facade), with the reasoning — why the hop value object is skeleton while the catalogue that produces the list stays use-case-specific — recorded in ADR-0009 decision 2, LLD §11.1 and the plan's item 2.
- **Finding 2 [major] — the permitted test change was understated as "only an import line".** It is now stated precisely as *"repoint a read, an iteration or a type annotation of a moved enum member at the family enum that now owns it"*, with the five affected test sites enumerated in ADR-0009 decision 3, the uniqueness/status-coverage test marked **strengthened** in scope, and the SRS traceability note's *"the extraction is wrong, not the tests"* sentence **qualified in place** (ADR-0009 decision 3, LLD §11.3, SRS note, plan items 3 and the two stage records).
- **Finding 3 [major] — the seam could not reproduce the two applications' reject/allow paths.** `PolicyDecision` now carries the reject trace summary, the reject log message, the reject extra trace/log fields and the allow-path originate log message plus extra log fields; the peer-status key is an **overridable** point (default `name:address:port`, anti-fraud overrides to `address:port` with a `"-"` fallback and never renders `fraud_sbc_peer`); the base stores the serving hop as a `NextHop` while `uaO` still receives the `(address, port)` tuple; and the per-application **strings vs forbidden branching** trade-off is stated honestly (ADR-0009 decision 4, LLD §11.2, plan item 4).
- **Finding 4 [major] — the lockfile guard was claimed to catch a library move; the design said otherwise.** ADR-0009 decision 6 now states the honest position: with a `path` source the lockfile **cannot constrain** the library's version, so the lock does **not** catch a move; `.github/workflows/ci.yml`'s lock comment is true for **registry** dependencies and **not** for the path dependency; **every CI job needs a second checkout**; what catches a skew is a **gate**; and the residual is an accepted gap for `docs/production-gaps.md` in the implementation commit (ADR-0009 decision 6, LLD §11.5 and §11.6, plan item 6).
- **Finding 5 [minor] — the "separate repository, not a uv workspace" fact was implicit.** It is now stated explicitly in ADR-0009 decision 1 and LLD §11.1.
- **Finding 6 [minor] — `docs/architecture/lld.md:12` listed `TrunkMessage` in the `sip_adapter.py` row.** `TrunkMessage` is removed from that row (it is deleted with the move, ADR-0009 decision 2).
- **Finding 7 [minor] — the plan record said `AGENT.md` §4.3 is updated "only if the maintainer rules that way".** Reconciled: §4.3 **is** updated in the implementation commit, because it is a structural document and `AGENT.md` §13 requires it (ADR-0009 decision 3, LLD §11.6, plan's obligations paragraph).
- **Finding 8 [minor] — the probe was a scratch directory that a reader could not re-run.** Its **reproducible form `tools/path_dependency_probe.py`** is added and registered in `tools/README.md`, cited in ADR-0009 as the reproducible form of its *Verified facts*, and it exits non-zero when any measured expectation does not hold (its recorded output is in ADR-0009 *Verified facts*). It is a design instrument, not a test: pytest does not collect it and it is not in `make test` or CI.

The gate record above is the stage's close. The HLD/LLD deltas the earlier records listed as
"not written" are now written (HLD §10, LLD §11), and the stage's own documents are internally
consistent (ADR-0009 vs HLD §10 and LLD §11 re-read).

**P10 implementation stage (stage 3) — the seven-step extraction, its nine judgements and its
review gate (2026-09-19).** The stage ran on `feat/platform-extraction`, cut from `phase2`,
across **two repositories**: this one, the application/reference implementation, and the new
library repository **`/home/shudong/project/as_platform`** (branch `main`, distribution
`as-platform`, package `as_platform`, `VERSION` `0.1.0`). The library has **no remote and has
never been pushed**, which bounds what the stage can claim about CI (below). The move is
ADR-0009 decision 7's seven steps, each its own commit, each leaving `make lint` clean and all
three layers green (REQ-F-033, D7, `AGENT.md` §10):

| Step | Commit | What it did |
| --- | --- | --- |
| 1 | `f041174` | `build(p10)`: add the `as-platform` path dependency (`editable = true`) and regenerate `uv.lock`. No code moves. |
| — | `65aa3c8` | `docs(p10)`: correct the ADR's attribution of the single-checkout failure (judgement 2). |
| 2 | `ac929a9` | `refactor(p10)`: move the leaf modules (`observability/`, the `errors` mechanism + `SkeletonErrorCode`, `sip_adapter`, `hop`) with the `as_app` facades; `TrunkMessage` deleted. |
| 3 | `efa4386` | `refactor(p10)`: move the version chain and the bootstrap plumbing; the anti-fraud now imports the shared modules from `as_platform` directly rather than through the `as_app` facades. |
| — | `9a59756` | `refactor(p10)`: drop the version helper the extraction orphaned. |
| 4 | `0319c8d` | `refactor(p10)`: rewire both controllers onto the shared shell (`BaseCallController` + `decide()` + `PolicyDecision`); −1404 lines here, the largest step. |
| 5 | `f341aff` | `refactor(p10)`: turn both `internal_api` modules into facades over the library shell. |
| 5 | `8ab507d` | `refactor(p10)`: derive both AS stacks from the library `BaseAsStack`. |
| 6 | `0b12db2` | `refactor(p10)`: bind the stack and the caller state to the new seams (transport, state store). |
| — | `2848f34` | `docs(p10)`: record the platform library in the structural documents and CI (`AGENT.md` §4.3/§5/§10, `README.md`, `docs/README.md`, `docs/production-gaps.md`; all five CI jobs gained the second checkout). |
| — | `042acdc` | `docs(p10)`: correct the ADR's `sip_adapter` carry list and the step-5 scope (judgements 4 and 5). |
| — | `b824f11` | `fix(p10)`: the gate's blocker — answer the trunk when the routing engine raises (judgement 9). |
| — | `f7249de` | `docs(p10)`: correct the documents the extraction left asserting the old sharing (the gate's major 3 and minor 4). |
| — | `07b68e4` | `docs(p10)`: correct the stale `SIP_PHRASES` 608 clause in the LLD. |

The library repository landed the same steps on its `main`, in order: `9eebe66` (leaf modules),
`ee02653` (the library's own `ruff`/`mypy`/`pytest` tooling), `7c1355b` (version chain +
bootstrap plumbing), `060ef71` (controller shell), `f82a819` (internal-API shell), `734d82c`
(AS stack shell), `d5e4561` (the transport and state-store seams), `d627e73` (step 7: the
library's own 11 test files, `docs/api-reference.md`, `docs/integration-guide.md`,
`docs/compatibility-matrix.md`, `Makefile`, `.github/workflows/ci.yml`, and the updated
`CHANGELOG.md` / `README.md` / `pyproject.toml`) and `aaa453e` (the blocker fix's library-side
docstring).

**Judgement 1 — the sixth test-change site, in the second bounded class.** Step 1's mandatory
`as-platform` entry in `[project].dependencies` collided with
`tests/unit/test_fraud_configuration.py::test_the_runtime_dependency_pin_is_unchanged`, which
asserted the literal substring `dependencies = ["sippy==2.4.2"]` and so could not survive a
second entry — `[project].dependencies` is one TOML array, and the design stage's enumeration
had missed this site. The assertion is now structural (`tests/unit/test_fraud_configuration.py`
`:321-322`): `sippy==2.4.2` is still asserted present, and the **exact set** of runtime
dependencies is now pinned (`set(runtime_dependencies) - {"sippy==2.4.2"} == {"as-platform"}`)
rather than left open, so the change can only strengthen. This is ADR-0009 decision 3's **second
bounded class**.

**Judgement 2 — the ADR's mis-attribution of the single-checkout failure (`65aa3c8`).** The ADR
had attributed *"a checkout with only this repository does not resolve `as-platform`"* to
*Verified facts* (a), the missing-source error. That is wrong: a single-repository clone already
carries `[tool.uv.sources]`, so it takes the `path` branch and fails with `Failed to generate
package metadata for as-platform==0.1.0 @ editable+../as_platform` / *cause: Distribution not
found at: file:///…* — the failure *Verified facts* (f) describes. Corrected to cite decision 6
and (f).

**Judgement 3 — the library gained three runtime dependencies.** `pydantic` (the moved
`hop.NextHop` is a pydantic model, as in the reference implementation), and `fastapi` +
`uvicorn[standard]` (the moved `internal_api` shell serves the console surface as a FastAPI
application on a daemon uvicorn thread, per ADR-0002, at the versions this repository pins). The
pinned `sippy==2.4.2` / Python 3.10 stack is unchanged — one sippy (ADR-0009 decision 1).

**Judgement 4 — the `sip_adapter` carry list was incomplete (`042acdc`).** ADR-0009 decision 2's
row and LLD §11.1's row named only seven of the **nine** public names the library actually
exports; `TRANSACTION_TIMER_NAMES` and `build_request_uri` were missing. Verified as an error and
not a deliberate exclusion: the pre-move file (`git show ac929a9^:src/as_app/sip_adapter.py`) had
a **ten**-entry `__all__` including both, and the only entry the move dropped is `TrunkMessage`
(deleted). Both rows now carry all nine.

**Judgement 5 — the `BaseAsStack` step-5 ruling (`042acdc`).** Step 5 of the staged sequence
named only `internal_api`, although ADR-0009 decision 2's module table lists `main` (shell) →
`BaseAsStack` as moving, and decision 7's own prose says "the stack depends on the controller and
`internal_api`". The commit sequence confirms where it actually went: library `f82a819`
(internal-API shell) → `734d82c` (AS stack shell) → `d5e4561` (the two seams), i.e. the stack
shell moved as the **second half of step 5**. **The ruling: the move belongs to step 5.**
`BaseAsStack` consumes both the controller shell (step 4) and `internal_api` (step 5) so it
cannot precede step 5, and giving it a step of its own would make the order eight steps and
contradict the "seven steps" both documents state. Both step-5 rows (ADR-0009 decision 7 and LLD
§11.7) now name the stack shell, and the sequence stays seven steps.

**Judgement 6 — the fraud reload callback keeps its historical name.** `FraudAsStack._poll_reload`
(`src/anti_fraud_as/main.py:203`) delegates to `_poll_screening_reload` (`:212`), keeping the
older name, because the integration tests drive `_poll_screening_reload` **directly**
(`tests/integration/test_fraud_screening_path.py`). The base's hook is `_poll_reload`; the
subclass method is the retained historical one, with the reason stated in its docstring.

**Judgement 7 — the logger name changed to `as_platform.main`, and the observable consequence is
nil.** After the stack shell moved, the library's `src/as_platform/main.py` logger is
`get_logger(__name__)` = `as_platform.main` (previously `as_app.main`), and the moved
controller's is `as_platform.call_controller`. The stage checked rather than assumed what that
costs, and four checks — each against the code — put it at **no observable difference on any
surface this repository renders**: (i) `StructuredFormatter` emits `record.module`, which CPython
derives from the **basename of the emitting file**, not from the dotted logger name — verified
directly by formatting a record with `name="as_platform.main"` and
`pathname=…/as_platform/main.py`, which renders `"module": "main"`, and both files are `main.py`
/ `call_controller.py` before and after the move, so the field stays `main` /
`call_controller`; (ii) `name` is in the formatter's explicit **excluded** tuple
(`as_platform/src/as_platform/observability/logging.py:100`), so it is never rendered into the
payload — verified: the payload's keys are exactly `LOG_FIELDS` and `"name"` is absent; (iii)
`configure_logging` installs its handler and its level on the **root** logger alone
(`logging.py:183-193`) and neither repository sets a per-logger level, handler or filter (no
`addFilter`; the sole `%(name)s` format string in either repository is the untouched standalone
SBC mock's own `logging.basicConfig`, `src/s_sbc_mock/main.py:274`), so nothing keys on the name;
(iv) no test or tool reads `record.name` (no `caplog`, no `assertLogs`). The live
`uv run python -m as_app.main --self-check-only` reproduces the pre-P10 bytes —
`{"…", "module": "main", …}` with exactly the field set of `docs/acceptance/report.md:1125` and
no `name` key. Recorded here as a judgement and deliberately **not** in
`docs/production-gaps.md`: the rename is internal identity only.

**Judgement 8 — `tests/unit/test_caller_state.py` was repointed (`0b12db2`).** Two boundedness
tests (`test_a_callers_window_is_bounded`, `test_the_store_is_bounded_across_callers`) asserted
the window's bound by reading the **private** deque (`store._window`, `bounded._window._events`),
which the state-store seam removed. They now assert the same property through the public
`store.observe(caller).calls_in_window` count. Registered as the **third** bounded class in
ADR-0009 decision 3 during the gate.

**Judgement 9 — the gate's blocker, and the guard the move silently dropped (`b824f11` + library
`aaa453e`).** Pre-P10, `CallController._originate_outbound_leg` wrapped the policy call in
`try:` / `except AsError as reject_error: self._reject_on_trunk(reject_error)` (see
`git show ac929a9^:src/as_app/call_controller.py`), and pre-P10 `apply_call_policy` **raised**
`AsError` for a non-routable decision. Post-P10 the seam became errors-as-data (`decide(event) ->
PolicyDecision`), the base calls `apply_call_policy` with **no** guard, and the
number-translation `decide()` called `route_call` with no guard either — so an `AsError` from the
routing engine escaped `decide()` → `_originate_outbound_leg` → the sippy event callback and the
caller saw **no final response** instead of the trunk answer. Two reachable paths: `AS-ROUTE-004`
/ `500` ("translation produced an empty number", `src/as_app/routing/engine.py`, when a rule's
`strip_prefix` consumes the whole number) and `AS-ROUTE-003` / `480` (a hop a matched rule names
that cannot be resolved at runtime, `RuleSet.next_hops_for`). The existing test stopped at the
engine (`test_translation_to_empty_yields_500` asserted the raise, never driving the controller),
which is exactly why all three layers stayed green while `REQ-F-031` was broken on this path.
**The fix**: the application owns the conversion (ADR-0009 decision 4 — the base applies data and
is forbidden to branch on "which application am I", so it cannot build the application's reject
vocabulary); `CallController.decide()` now catches `AsError` and returns a reject
`PolicyDecision` sharing one `_reject_decision` construction with the existing non-ROUTE branch
(`src/as_app/call_controller.py:137-149`, `:310`), reproducing the pre-P10 trunk answer: the
error's own status and phrase, disposition `REJECTED`, trace `rule_id=None` with `"rule_id": ""`
beside `leg` and `error_code`, summary `"<status> <phrase> relayed to the trunk leg"`, and the
WARNING `"call rejected by routing policy"` with `error.as_log_fields()`. The library's abstract
`decide()` docstring now states the contract (the application returns a reject decision for a
failure it cannot relay and does not let `AsError` escape; a `RELAY` decision always names at
least one hop), and the same contract was added to ADR-0009 decision 4 and LLD §11.2. Two
regression tests were added to `tests/integration/test_translation.py` driving the **real stack**
and asserting the status line on the trunk (`:468`
`test_translation_to_empty_is_answered_500_on_the_trunk`, `:486`
`test_unresolvable_hop_is_answered_480_on_the_trunk`); the other test's docstring, which claimed
the controller turned the failure into a `500` on the trunk without asserting it, was corrected
to point at the new test.

**The implementation-stage review gate.** Run by an **independent read-only** agent (it edited
nothing, and wrote no part of the stage). It asked the §5.2 *Implementation* question —
**"matches the design, stays in scope, no shortcuts taken silently"** — and returned
**PASS-WITH-FINDINGS — one blocker, two major and two minor findings**, all of which were
**fixed inside the stage** and the stage is **not re-reviewed** (§5.2, "one review per stage, no
loop"). The five findings and their fixes:

- **[blocker] `AS-ROUTE-004` no longer reached the trunk** — the dropped guard and its fix,
  judgement 9 above (fixed in `b824f11` + library `aaa453e`).
- **[major] `tests/unit/test_caller_state.py` was a third class of test change, and it was
  unrecorded** — recorded as the third bounded class in ADR-0009 decision 3 (judgement 8;
  `f7249de`).
- **[major] `docs/architecture/hld.md` had not been touched by any P10 commit, and its §10.3
  contradicted the implementation** — three corrections: the §10.1 mermaid edge asserting the
  anti-fraud "imports as_app's skeleton surface (ADR-0007 decision 9)" is now the version chain
  only (`from as_app import __version__`, the sole remaining `as_app` import in that package);
  the §10.3 sippy-adapter row gained the two missing names (matching `042acdc`); and the §10.3
  one-way-direction paragraph now states that the anti-fraud imports the **library** directly,
  so the extraction replaced ADR-0007 decision 9's *mechanism* while that decision's *substance*
  ("a second process, not a framework") still holds, with `src/as_app/**` ↛ `anti_fraud_as`
  (REQ-F-026, REQ-F-030) unchanged (`f7249de`).
- **[minor] `docs/architecture/lld.md` §4 and §9.1 still asserted the pre-extraction structure**
  — §4's `AS-FRAUD-*` note now records the split by family over one shared mechanism (pointing
  at §11.3) and drops a stale present-tense clause about `SIP_PHRASES` having no `608` entry;
  §9.1's sharing table is now sourced from the library and its `internal_api` row records that
  P10 collapsed the deliberate duplication into facades. A fourth, same-class stale clause in
  §9.5 (the identical `608` claim) was found during the fix and corrected in `07b68e4`, so the
  document does not contradict itself (`f7249de`, `07b68e4`).
- **[minor] `tests/unit/test_fraud_configuration.py`'s `ALLOWED_IMPORTS` allowlist was widened
  without being registered** — the allowlist necessarily gains the library when the import
  target moves; registered as the **fourth** bounded class in ADR-0009 decision 3 (`f7249de`),
  with the bound that keeps it honest recorded (the fixture still enumerates its set exactly and
  still fails on any module outside it).

The gate verified, and did not merely take on trust: the library imports **neither** `as_app` nor
`anti_fraud_as` (REQ-F-030); the five facades are pure re-exports with no behaviour or state and
every by-path reference still resolves; the seam reproduces both applications' allow and reject
paths with **no** branch on "which application am I" (the peer-status-key override and the one-leg
relaxation are as designed); the error split is **byte-identical** in every code, SIP status and
log message (checked against `git show ac929a9^:src/as_app/errors.py`); `TrunkMessage` is gone;
the two seams have exactly one implementation each and no TLS, no Redis and no capacity harness
were built (that is P11's, REQ-NF-020); and the structural documents and all five CI jobs were
updated with the honest position about the lock not guarding a `path` dependency. It noted that
ADRs `0001`–`0008` are frozen historical records and deliberately not updated.

**The verification the stage leaves behind** (independently re-run after all fixes):

- application repository: `uv run ruff format --check .` → `95 files already formatted`;
  `uv run ruff check .` → `All checks passed!`; `uv run mypy` → `Success: no issues found in 29
  source files`; `uv run pytest tests -q` → **`248 passed`** (246 before the two regression
  tests).
- library repository: `uv run ruff format --check .` → `31 files already formatted`;
  `uv run ruff check .` → `All checks passed!`; `uv run mypy` → `Success: no issues found in 15
  source files`; `uv run pytest -q` → **`74 passed`**.
- the library-independence grep over `as_platform/src/` for `as_app|anti_fraud_as` returns **no
  matches**.
- **CI cannot be run, and the record says so honestly**: the library has no remote and has never
  been pushed, so the `git clone https://github.com/${{ github.repository_owner }}/as_platform.git`
  URL in every CI job is an **assumption**, and CI is not green until the library is published —
  already a row in `docs/production-gaps.md`.

**The blocker's independent confirmation.** When the fix was temporarily removed, both new tests
failed with an empty status line (`assert '' == 'SIP/2.0 500 Server Internal Error'` / `…
'SIP/2.0 480 Temporarily Unavailable'`, `2 failed`), which is the evidence that the tests
genuinely fail without the change. The fix restores the pre-P10 bytes, and the new tests are what
stops it silently breaking again.

**State after stage 3.** Stages 1–3 of P10's §5.1 pipeline are complete and their review gates
have run — the requirements and design records are earlier in this subsection, and the
implementation record and its gate are this one. The gate's five findings were fixed **inside the
stage** (`b824f11`, library `aaa453e`, `f7249de`, `07b68e4`) and the stage is **not re-reviewed**
(§5.2). **The tests stage is next** — it is stage 4 of the §5.1 pipeline, and the acceptance
stage (stage 5) follows it — so `ACC-P10-001…008` remain to be created there.

**P10 tests stage (stage 4) — the tests that carry the extraction, and their review gate
(2026-09-20).** Under §5.1 the artefact of this stage is **tests**, not documents. The
implementation stage had already added the two trunk-answer regression tests of judgement 9
(`tests/integration/test_translation.py`, `b824f11`) and step 7 had given the library its own
suite (`d627e73`); what this stage added is tests for the requirements that had **no direct test
at all** before it — the two `REQ-NF-` rows, `REQ-F-029`'s *user* half and `REQ-F-032` — plus the
two anti-fraud controller overrides that until now were evidenced by **inspection only**.

**A correction, recorded rather than made silently.** The paragraph above used to end "the
acceptance stage is next, and `ACC-P10-001…008` remain to be created there". That contradicted
§5.1, where stage 4 is Tests and stage 5 is Acceptance, so at the time it was written the tests
stage had not run yet. The sentence was corrected to name the tests stage as the next one (this
commit) and the correction is stated here so the record does not disagree with the pipeline.

**Requirement → test coverage.** Each row names the test that carries the requirement; a
requirement with no test says so instead of being claimed.

| Requirement | The test that carries it |
| --- | --- |
| `REQ-F-029`, user half | application repository `tests/unit/test_repository_baseline.py::test_both_as_instances_are_users_of_the_platform_library` |
| `REQ-F-030` | library `tests/test_library_independence.py`; application `::test_as_app_does_not_import_the_anti_fraud_as` |
| `REQ-F-031` | the three layers, the two trunk-answer regression tests, and `tests/unit/test_fraud_call_controller.py`'s four override assertions |
| `REQ-F-032` | application `::test_the_library_is_consumed_from_the_sibling_checkout` (dependencies, `[tool.uv.sources]` `path`, `editable = true`) |
| `REQ-NF-019` | library `tests/test_library_standard.py` (the three documents, the application set not copied) plus the workspace rows added here |
| `REQ-NF-020` | library `tests/test_seams.py` (four tests) |
| `REQ-NF-021` | library `tests/test_library_standard.py`'s Makefile, CI and `pyproject.toml` assertions |
| `REQ-F-033` | **no test** — see the honest gaps below |

**Two requirements are deliberately not asserted, and that is stated rather than papered over.**
`REQ-F-033` — the extraction is done in incremental steps and each step leaves the three layers
green — is a **process and historical property**, evidenced by the commit sequence and by the
layer runs, not by an assertion a test can make; inventing one would assert nothing. The other
half of `REQ-F-029` — *this repository becomes the library's reference implementation* — is a
**role statement**, not a property of the artefacts, so only its user half is asserted.

**The bounded test classes are limited to the extraction's own edits (`8c0166d`).** ADR-0009
decision 3's four bounded classes constrain the edits the **extraction** — the implementation
stage — makes to the existing suite; the Tests stage **adds** tests as its own deliverable, which
is neither inside those four classes nor in conflict with them. The ADR's closing sentence was
scoped to say exactly that. The maintainer's ruling also reviewed the one test this stage added
beyond the agreed list: `test_both_as_instances_are_users_of_the_platform_library` was proposed
as revertible and was **ruled kept**, because *both instances become users of that library* is a
clause of `REQ-F-029` itself and therefore an assertable half of it.

**The red signal.** Each assertion was shown to fail for the production change it guards, by
removing the change, observing the failure and restoring the bytes. The producer's own mutations,
in a temporary copy or against `cp`-saved bytes: deleting `FraudCallController._peer_status_key`
made the base default render the internal hop name — `assert 'fraud_sbc_peer' not in
'fraud_sbc_peer:10.0.0.1:15062'`; deleting `_no_answer_hop_label` lost the address and port —
`assert '' == '127.0.0.1:15061'`; adding `tlsconfig.py` or `redis_store.py` under
`src/as_platform/` tripped the seam vocabulary (`a P11-only module is present in P10:
['tlsconfig.py']`); adding a `[tool.uv.workspace]` table to either `pyproject.toml` or renaming
the library distribution tripped the workspace rows (`'[tool.uv.workspace]' is contained here`).
`test_the_peer_status_key_never_renders_the_internal_hop_name` is **not vacuously true** —
removing the override does fail it, and the name it excludes is the configured pipe name
`fraud_sbc_peer`, never the rendered value.

**The quality gate of this stage.** Run by an **independent read-only** agent that wrote no part
of the stage. It asked the §5.2 *Tests* question — **"the tests genuinely fail without the
change, coverage matches the requirements"** — and returned **PASS-WITH-FINDINGS: 0 blocker, 0
major, 5 minor**, all fixed **inside the stage** and not re-reviewed (§5.2, "one review per
stage, no loop"). It reproduced the red signals independently rather than trusting the record:
it copied both repositories to `/tmp` (excluding `.venv`, with the copy's `src/` overriding the
editable installs) and ran **18 mutation groups, every one of which turned red**, without
touching either working tree. It verified the exact scope (`git diff --numstat` — application
`tests/unit/test_fraud_call_controller.py` `88/0`, `tests/unit/test_repository_baseline.py`
`52/0`, the ADR `+4/-2`; library `117/0` and `89/0`), **zero deleted tests**, **zero loosened
existing assertions**, **zero `src/` changes**, that the new unit tests carry the `unit` marker
(`-m unit` → `209 passed`), that `test_fraud_call_controller.py` constructs its objects without
opening a socket or reading a clock (§11's unit layer), that **no document enumerates this
stage's new test sites** — so no document went stale — and that the four gate commands and their
numbers matched the record verbatim.

**The five findings and their dispositions.**

- **[minor] `REQ-NF-019`'s "not a uv workspace monorepo" clause had no test** — the manifests
  were asserted to *be* a `path` source but never asserted *not* to be a workspace member. Fixed
  in the stage: the library asserts its own half in
  `tests/test_library_standard.py::test_the_library_is_a_standalone_distribution_not_a_workspace_member`
  (no workspace table, and `[project]` self-reports `as-platform`) and the application asserts its
  half in `tests/unit/test_repository_baseline.py::test_the_library_is_not_a_uv_workspace_member`
  (library `0eeef37`, application `b1aef5a`). Neither test reads the other repository's directory,
  so the check does not couple to a sibling name.
- **[minor] `tests/test_seams.py`'s module-name check could be bypassed by a non-underscore
  name** — `stem.split("_")` caught `tls_config.py` but **not** `tlsconfig.py`. Tightened to a
  lower-cased **substring** match over the stem (library `0eeef37`), with the boundary stated in
  the test's docstring: it matches **module names**, not module content or class names; the
  `*Transport` / `*StateStore` class-suffix check is unchanged and stays out of scope for names
  like `TransportFactory`. Red signal: both `tlsconfig.py` and `redis_store.py` now fail it.
- **[minor] `test_the_peer_status_key_never_renders_the_internal_hop_name` is a strict subset of
  `test_the_peer_status_key_is_the_address_and_port`** — **kept** and registered as *redundant but
  not vacuous*, following the precedent of P9's stage-4 gate (§3), where two same-source
  assertions were registered and kept. It records an **independent intent** — the configured pipe
  name `fraud_sbc_peer` never reaches the peer-status counter — and deleting it would drop that
  intent's explicit guard.
- **[minor] neither repository's `mypy` covers `tests/`** — pre-existing configuration, not
  introduced by this stage (both manifests list only their `src/` packages). Recorded as an
  **accepted limitation** rather than changed here: widening a repository-wide gate is a
  maintainer decision, outside a test stage's scope. **Escalated to the maintainer** as a
  gate-scope question (whether `tests/` should be type-checked at all).
- **[minor] the stage's gate numbers and its two honest no-assertion statements existed only in
  the commit message** — closed by this record, which is the repository-side home for both.

**The verification this stage leaves behind** (run after all fixes):

- application repository: `uv run ruff format --check .` → `96 files already formatted`;
  `uv run ruff check .` → `All checks passed!`; `uv run mypy` → `Success: no issues found in 29
  source files`; `uv run pytest tests -q` → **`255 passed`** (246, then 248 after the
  implementation stage's blocker fix, then 254 for this stage and 255 after finding 1).
- library repository: `uv run ruff format --check .` → `33 files already formatted`;
  `uv run ruff check .` → `All checks passed!`; `uv run mypy` → `Success: no issues found in 15
  source files`; `uv run pytest -q` → **`84 passed`** (74, then 83 for this stage and 84 after
  finding 1).

**State after stage 4.** Stages 1–4 of P10's §5.1 pipeline are complete and their review gates
have run. This stage's gate returned PASS-WITH-FINDINGS and its five findings were fixed **inside
the stage** (library `0eeef37`, application `b1aef5a`, plus the ADR scoping of `8c0166d`), so the
stage is **not re-reviewed** (§5.2). The acceptance stage (stage 5) is next, and
`ACC-P10-001…008` will be created there.

**P10 acceptance stage (stage 5) — `ACC-P10-001…008`, the §4.8 evidence and its review gate
(2026-09-20).** Under §5.1 the artefact of this stage is **acceptance**. The eight rows live in
`docs/acceptance/criteria.md` under `## Phase 2 — P10 platform extraction` (`:89-100`), one row
per requirement (`REQ-F-029…033`, `REQ-NF-019…021`) with the criterion, a reproducible command,
the expected result carrying the real numbers, and the requirement; the run record is the P10
section of `docs/acceptance/report.md` (`:2826-3260`), whose four sections follow `AGENT.md` §4.8
and whose `Evidence kinds per item` matrix states, per item, which kind is present. The stage
changed **no** code, test, ADR or architecture file: its range is exactly the two acceptance files
(`git diff --name-only d57c309..225a851` → two paths, `449 insertions, 0 deletions`).

**What the stage cannot supply, stated rather than substituted.** Kind ③ — the CI result — is
unavailable in **both** repositories. The library has **no remote and has never been pushed**, so
its own three-job workflow is an **unexecuted definition** with no run, badge or job conclusion;
and this repository's five CI jobs each clone the library into `../as_platform` before
`uv sync --frozen`, a clone that cannot succeed while the library exists nowhere but a filesystem,
so this repository's CI **cannot be green either** (`docs/production-gaps.md` `:134`, *CI second
checkout (new dependency)*, and `:131`, *Library gate not in this repository's CI*). There is **no
pcap**: `docs/specs/message-samples/` is generated and gitignored, so `make capture` produces 14
text samples plus their `README.md` — a message-sample set, not a capture — and no other capture
path exists for P10. The consumption probe measures `uv` against a **two-module stand-in**, not
the real skeleton (`:133`, *Consumption probe's stand-in scope*), and "a clone without the sibling
cannot resolve `as-platform`" is recorded as `REQ-F-032`'s **accepted cost** rather than asserted,
because this working tree *has* the sibling. `ACC-P10-007`'s per-step green is a **historical**
property with no test behind it, and a faithful per-step re-run is awkward rather than impossible:
the library is a `path` + `editable` dependency, so re-running step *n* means materialising **both**
repositories at their step-*n* commits — steps 1 and 4 were spot-checked from temporary worktrees
(`246 passed` each, `94` / `95 files already formatted`) and the other five rest on the commits'
own gate runs, which the record says instead of implying coverage.

**The requirement rows keep their status in this stage.** The git history decides that, and it does
not show the acceptance stage flipping them. For P9 the four rows were **added** `planned` in
`577d258 docs(p9): add chained-demo requirements to the SRS`, and `git show
f68ed27:docs/requirements/functional-and-nonfunctional.md` still reads `planned` at the acceptance
commit `f68ed27 docs(p9): add the P9 acceptance items and their evidence`; only
`06f8ed9 chore(p9): close the item — SRS, demo docs, version 0.7.0 and CHANGELOG`, a descendant of
both acceptance commits (`f68ed27`, `4d3e924`), set seven rows to `done | P9`. P8 flipped the same
way — `4d32e80 chore(p8): close the item` does not touch the SRS at all, and `d22324e docs(p8): mark
the P8 requirements done` (a descendant of the close) set fourteen rows — so status flipping is an
**item-close (§5.4)** action, not an acceptance-stage one. `REQ-F-029…033` and `REQ-NF-019…021`
therefore stay `planned` here and are set `done` by the §5.4 closing commit.

**The quality gate of this stage.** Run by an **independent read-only** agent that wrote no part of
the stage. It asked the §5.2 *Acceptance* question — **"the §4.8 evidence is real, reproducible and
complete"** — and returned **PASS-WITH-FINDINGS: 0 blocker, 2 major, 0 minor**, both fixed **inside
the stage** and not re-reviewed (§5.2). It re-ran every command in the record and matched them
verbatim (`1 passed, 55 deselected` / `2 passed, 54 deselected` / `1 passed, 55 deselected` /
`210` / `36` / `9`; the probe's `cases measured : 8` with `expectations : all held` and exit `0`;
the independence grep exiting `1` with no output; the library's `2`, `6` and `4 passed` and its
`33 files already formatted` + `84 passed`; the CI job list `['lint', 'test', 'type']`; `VERSION`
`0.1.0`). It materialised step 1 **read-only** (`git archive` of application `f041174` with library
`4caec3e`, in `/tmp`) and reproduced all four gates there — `94 files already formatted`,
`All checks passed!`, `28 source files`, `246 passed in 35.37s` — matching the record word for
word; ran `make capture` (14 samples, no pcap); ran both `-s` e2e files and confirmed §2's quoted
traces have the shape of a real capture rather than an invented one; checked the four-kind matrix
item by item for a silently omitted kind; confirmed the stage's range is exactly two files; matched
`docs/production-gaps.md` `:131-134` row for row; and confirmed the local gate was never presented
as a CI result.

**The two findings and their dispositions.**

- **[major] the `ACC-P10-002` row asserted a fact the extraction had already invalidated.** The row
  said `src/anti_fraud_as/call_controller.py` imports `as_app.sip_adapter`, but after P10 that
  module's line **57** imports `as_platform.sip_adapter` and the package's only remaining `as_app`
  **import** is the version chain at `src/anti_fraud_as/__init__.py:31` — the correction HLD §10.3
  and the stage-3 record already carry. Fixed in the stage: the row now states the **current**
  mechanism (and cites ADR-0009 decision 2 / HLD §10.3) while keeping the conclusion it existed for
  — only the one-way invariant is assertable, and only it is asserted.
- **[major] the same stale sentence made two P9 statements outdated, and the P10 record had not
  registered it.** `ACC-P9-001` in `docs/acceptance/criteria.md:83` and the P9 accepted-limitation
  bullet in `docs/acceptance/report.md:2796` still describe the P9-era import. Both were **really
  true when P9 ran**, so neither was rewritten: each now carries a minimal **P10-era note** saying
  the mechanism changed (the controller imports `as_platform.sip_adapter` directly; the only
  `as_app` import left in the package is the version chain) and that the one-way invariant the note
  justifies is unchanged (ADR-0009 decision 2, HLD §10.3). The P10 section and the eight rows were
  then re-read for the same substance — no other statement carries it.

**The verification this stage leaves behind** (run after both fixes):

- application repository: `uv run ruff format --check .` → `96 files already formatted`;
  `uv run ruff check .` → `All checks passed!`; `uv run mypy` → `Success: no issues found in 29
  source files`; `uv run pytest tests -q` → **`255 passed`**; `tools/path_dependency_probe.py`
  exit `0`.
- library repository: `uv run ruff format --check .` → `33 files already formatted`;
  `uv run ruff check .` → `All checks passed!`; `uv run mypy` → `Success: no issues found in 15
  source files`; `uv run pytest -q` → **`84 passed`**.

**State after stage 5.** Stages 1–5 of P10's §5.1 pipeline are complete and their review gates have
run; this stage's gate returned PASS-WITH-FINDINGS and its two findings were fixed **inside the
stage**, so the stage is **not re-reviewed** (§5.2). What remains is P10's **item close of §5.4**:
run the §16 Definition of Done, update this plan and the `docs/roadmap.md` pointer, update
`CHANGELOG.md` and `VERSION`, and commit — **no tag and no push** (`AGENT.md` §13 and §15). The
requirement status rows flip to `done` there, not here.

- **Status: done (2026-09-20), worked on `feat/platform-extraction` (this repository) and `main`
  (the library repository); merged into `phase2` as the final step of this close (§4 — an item
  branch merges into `phase2` when the item's own definition of done is met) and `main` is
  untouched; not tagged.**
  Stages 1–5 of §5.1 were completed, each with its own read-only review gate (§5.2), and the item
  close of §5.4 was then performed: the eight SRS rows `REQ-F-029…033` and `REQ-NF-019…021` are
  `done`; `VERSION` / `pyproject.toml` / `uv.lock` were bumped together to **`0.8.0`** and the
  CHANGELOG node `[0.8.0] - 2026-09-20` opened; acceptance items **`ACC-P10-001 … ACC-P10-008`**
  were accepted with evidence in `docs/acceptance/report.md`; and the §16 Definition of Done was
  run and recorded in that report's new `### Definition of Done` section. The **library repository
  keeps its `VERSION` at `0.1.0` and opens no new node**: its `[0.1.0]` node already declares that
  `0.1.0` was never released, tagged or pushed, so it describes the whole extraction, and the
  close only adds one `Added` bullet for the boundary tests `27fe26e` and `0eeef37` (library
  commit `801181c`). The `Call-ID` entry under `[Unreleased]` in this repository's `CHANGELOG.md`
  stays where it is (ruling below). Merging into `main` and tagging remain the maintainer's steps
  (`AGENT.md` §13/§15).

**One correction, stated rather than made silently.** The `**State after stage 5.**` paragraph
above lists the remaining close work — run the §16 Definition of Done, update this plan and the
`docs/roadmap.md` pointer, update `CHANGELOG.md` and `VERSION`, and commit — and does not mention
merging into `phase2`. Merging into `phase2` is also part of this close under §4 ("item branches
are cut from `phase2` … and merge into `phase2` when that item's own definition of done is met"),
and it was performed as the close's final step. This is a correction of that list, not a silent
edit of the stage-5 text: the paragraph above is left exactly as it was written.

**What was learned (2026-09-20).**

1. **An item that spans two repositories stretched §4.8's evidence model into a new shape.** Kind
   ③ is unproducible in **both** repositories: the library has no remote and has never been pushed,
   so its three-job workflow is an **unexecuted definition**, and this repository's five CI jobs
   each clone a sibling that cannot be cloned while it exists only on a filesystem. P8's and P9's
   version of the gap was "nothing is pushed"; P10's is "the sibling exists only on disk" — a gap
   only the maintainer publishing the library can close, and `docs/production-gaps.md` now carries
   two rows for it (`:131`, `:134`).
2. **`path` + `editable` makes "staged and green at every step" checkable only by sampling.**
   Re-running step *n* means materialising **both** repositories at that step's commits, so
   `REQ-F-033` / `ACC-P10-007` spot-checked only steps 1 and 4 while the other five rest on the
   commits' own gate records. The per-step green is a property of **the commits**, not of the
   current working tree, and the record says so instead of implying coverage.
3. **A structural refactor invalidates statements scattered far from the code it moved, and only
   an independent read-only gate takes the record back to the tree.** Both of the acceptance
   gate's major findings were stale facts the **extraction itself** left behind: `criteria.md`'s
   `ACC-P10-002` still said `src/anti_fraud_as/call_controller.py` imports `as_app.sip_adapter`,
   and the same sentence had also outdated `criteria.md:83`'s `ACC-P9-001` and `report.md:2796`'s
   P9 accepted-limitation. The handling was a minimal **P10-era note** on the P9 statements, not a
   rewrite of history — add the note, do not delete or reword the old claim.
4. **A new test must be mutation-checked to prove it is not vacuous.** `test_library_standard.py`'s
   first form used substring matching, so `pytest` was satisfied by `.pytest_cache` and `mypy` by
   the job step name `- name: mypy`; after tightening it to parse the `Makefile` recipe lines and
   the CI `run:` lines, the mutations turned red honestly. **An assertion a grep happens to
   satisfy is not a test.**
5. **The move took about 3.4k lines out of `src/` (21 files), and the item branch touched 48
   files in all, with the wire bytes unchanged.** The acceptance evidence for a pure refactor is
   therefore not a new-feature demo but **unchanged behaviour** — the same Call-ID keyed trace
   shape and the same `-b2b_1` derivation (`ACC-P10-003`'s §2/§4).

**Entry state for P11.**

- P11 works **in the library repository** per the §4 table, starting from the library's `main`
  after this close. The library has no branch of its own yet, and creating one needs the
  maintainer's approval (`AGENT.md` §13) — the §8 blanket grant of 2026-09-19 ("full authority to
  judge and execute through the end of Phase 2") covers it, but the purpose and the end condition
  still have to be stated. This repository's working tree is `phase2` after the close.
- P11's **design stage includes** the sippy TLS-support probe (`AGENT.md` §14 forbids assuming;
  §7 item 5). The probe belongs to P11's design stage and does not move earlier (§5.1).
  Certificates are produced by a generation script and **no private key is ever committed**
  (`AGENT.md` §9); Redis runs as a `docker compose` service and the **in-memory store stays the
  default**, so `make demo`, the three layers and CI keep running with no external service; the
  harness **reports constraints only and never publishes a figure** (D10).
- **P11's first edit** is the library's `tests/test_seams.py` and `tests/test_library_standard.py`:
  they now **deliberately** forbid a second implementation and any TLS / Redis / harness module
  (`REQ-NF-020`, `ACC-P10-006`, the report's accepted-limitation entry). P11 rewrites those
  assertions by design and must also re-examine `REQ-NF-002` (UDP-only) — `REQ-NF-020` already
  states that the TLS supersession happens in P11.
- `path` + `editable` means a library change reaches this repository **immediately**, so both gates
  must run (library `make lint` / `make test` and this repository's `make lint` / `make test`), and
  the `as-platform` entry in `dependencies` carries no version constraint.
- Neither repository has CI (the library has no remote; this repository's five jobs need the
  sibling), so **P11 inherits the same kind ③ gap** unless the maintainer publishes the library.

**Two rulings, recorded so a later conversation does not re-derive them.**

- **The `Call-ID` entry stays under `[Unreleased]` and is not folded into `[0.8.0]`.** It belongs to
  the **Phase 1 `main` fix** (`d8dad31`, `f1b4186`, landed on `main`; §7 item 8 — "its own
  conversation owned its `CHANGELOG` / `VERSION`"), not to P10. `06f8ed9` deliberately left it at
  the top of `[Unreleased]` (Keep a Changelog puts `Unreleased` first), and it was never released
  under any version node, so leaving it as it is stays truthful.
- **The library keeps `VERSION` `0.1.0` and opens no new node.** Its `[0.1.0]` node states it was
  never released, tagged or pushed, so the whole extraction is described there; a second node for
  two test commits would misstate that. Only one `Added` bullet was added (library `801181c`).

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

- **Status: done (2026-09-20), worked directly on `main` of the library repository** and on
  `phase2` of this repository — no item branch was needed (§4 table: "branches in the new
  repository" and the §8 blanket grant covers it; creating one needs a stated purpose and
  end condition, and P11 had neither — the item is the final Phase 2 work). Stages 1–5 of
  §5.1 were completed, each with its own read-only review gate (§5.2). Acceptance items
  **`ACC-P11-001 … ACC-P11-006`** accepted with evidence in `docs/acceptance/report.md`;
  the **library repository** was bumped from `0.1.0` to **`0.2.0`** and opened a dated
  `[0.2.0] - 2026-09-20` CHANGELOG node; this repository was bumped from `0.8.0` to
  **`0.9.0`** and opened a P11 entry under `[Unreleased]`. Both repositories' gates are
  green — the library `make check` reports **`99 passed, 5 skipped`** (the 5 skipped are
  the `RedisStateStore` tests, correctly gated by `pytest.skipif` when no Redis is
  reachable), and this repository's `uv run pytest -q tests/unit/` reports **`210 passed`**
  — the widened `NextHop.transport` field and the Protocol lifecycle methods P11 added
  are purely additive, so zero consumer code change was required. Merging into `main`
  and tagging remain the maintainer's steps (`AGENT.md` §13/§15), and the library has no
  remote to push to.

**What was learned (2026-09-20).**

1. **sippy's TLS is genuinely absent, not merely undocumented.** Probing `SipTransactionManager.newTransaction()` confirmed it handles only `udp`, `ws`, `wss` and raises `RuntimeError` on anything else; there is no `Tcp_server` or `Tls_server` class, and `SipConf.default_transport` is hard-wired to `udp`. The bridge approach (`TlsTransport` terminates TLS outside sippy and feeds it through a local UDP socket) was the right call — it proves the Transport seam is pluggable *without* pretending sippy supports what it does not — and it is a real deployment pattern (OpenSIPS / Kamailio TLS termination in front of UDP-originating AS instances). That said, AS-originated SIPS outbound remains a gap because it would require subclassing sippy's `Network_server`.
2. **`StateStore.start()` / `stop()` are worth their weight.** The lifecycle methods added to both Protocols look like gratuitous Protocol pollution — `UdpTransport` and `InMemoryStateStore` supply no-ops — but they are exactly what lets `TlsTransport` and `RedisStateStore` own their sockets and threads, respectively, without any caller `hasattr` branching. `BaseAsStack.start()` calls `transport.start()` *before* `sip_config()` precisely because `TlsTransport.sip_config()` needs its local UDP port allocated first. This is the abstraction paying for itself: the seam was designed to have the second implementation fit, not to have its callers special-case the first.
3. **A library that owns `ED2` calls `ED2.callFromThread()`, not `.dispatchTimers()` directly.** The capacity harness measures the loop gap by scheduling one callable onto `ED2` and comparing its actual fire time to a wall-clock marker; calling `.callFromThread()` is safe from non-ED2 threads. Calling `.dispatchTimers()` directly — a tempting shortcut — races with the loop's own `select()` and produces nonsense measurements. The harness got this right on the first try because P8a's "how sippy owns its timers" note in §3 already established the pattern.
4. **The ruff `D102` per-test-class rule is cheap.** The library's `pyproject.toml` had `"tests/*" = ["D104"]` only; `test_state_store.py` gained a class `TestRedisStateStore` whose un-documented methods turned ruff red. Adding `D102` to the per-file ignores — `"tests/*" = ["D102", "D104"]` — is cheaper than docstring-per-test, and the library test modules each carry a full module docstring already.
5. **`pyproject.toml`'s `module` pattern for mypy overrides is fussy.** `module = ["redis*"]` is invalid — mypy wants `["redis", "redis.*"]`. That tiny mistake took about 15 minutes to debug because mypy's error ("cannot find module 'redis'") is identical for both the wrong pattern and a genuinely missing module.

**Phase 2 is complete.** P11 is the last item in §3; there is no entry state for a next item. The closing work of §5.4 — updating this plan and `docs/roadmap.md`, bumping versions and opening CHANGELOG nodes — is done above; what remains is the maintainer's call on whether and when to merge `phase2` into `main`, push the library, and tag.

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
- **Chained Call-IDs.** Two B2BUAs in series mean several Call-IDs; correlation across AS
  instances has to be solved, not assumed away (P9). *(True again, and now for **both** AS
  instances: the number-translation instance was fixed on `main` and merged back on
  2026-09-19, and the anti-fraud instance's own copy of the same defect is fixed in P9's
  implementation stage — §3 P9, findings (A)–(C).)*

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
8. **Phase 1 `Call-ID` defect — fixed and merged back; closed 2026-09-19.** The AS reused
   the inbound `Call-ID` on its outbound leg, contradicting the design intent of
   `docs/architecture/lld.md` §2.3; the maintainer ruled it a **Phase 1 defect**, not an
   accepted deviation. It was fixed as a **separate item in a separate conversation**, on
   **`main`** (`f1b4186`, plus `d8cabad` for the dead-code removal), merged back into
   `phase2` (`76a95da`, `1676b6d`) with the one phase2-only call site adapted (`d26d5c4`),
   and the pause on P9 is lifted. Its own conversation owned its `CHANGELOG` / `VERSION` and
   any `ACC-*` row, so nothing about the fix is registered **here**; what it left behind is
   §3 P9, findings (A)–(C). **Not pushed, not tagged.**
9. **Phase 2 integration timing flake — registered 2026-09-19, not fixed.**
   `tests/integration/test_fraud_screening_path.py::test_a_broken_edit_keeps_the_previous_screening_data`
   fails with `AssertionError: ... status=500` in roughly one run in six, together with
   `anti_fraud_as.call_controller: next hop did not answer in time`. It is green in isolation
   and the failure is a timing race around the relayed leg's **3-second** no-answer timeout
   (`_DEFAULT_NEXT_HOP_EXPIRE` in `src/anti_fraud_as/call_controller.py`). Row in
   `docs/production-gaps.md`. **Follow-up item, not part of P9** (`AGENT.md` §14 rule 4):
   the honest repair is to make the test deterministic — drive the timeout from a test
   setting, or wait on the trace event rather than on wall-clock — not to widen the timeout.
   The same precedent as item 7: register the harness defect rather than improvise a fix
   inside the item that happened to observe it.
10. **`REQ-F-026`'s wording versus the invariant that can be asserted — escalated to the
   maintainer 2026-09-19, by the stage-4 review gate of §3 P9.** The row says the two AS
   instances stay independent processes and that "neither AS imports the other", but
   `src/anti_fraud_as/call_controller.py` imports `as_app.sip_adapter` **by design** — the
   reuse of the use-case-agnostic skeleton, ADR-0007 decision 9 — so only `src/as_app` ↛
   `anti_fraud_as` is assertable, and only that direction is asserted
   (`tests/unit/test_repository_baseline.py`). The behaviour is correct and the test is
   honest; the **wording** is looser than the fact. A stage review may not reword a frozen
   requirement (§5.2), so the maintainer's call is: leave the row as it is and read
   "neither imports the other" as the one-way dependency it was meant to be, or tighten the
   clause to name the direction (which would also touch ADR-0008 decision 1, which repeats
   the phrase). **Registered, not fixed, and not blocking** — nothing in P9 depends on it.

## 8. Decisions requiring maintainer approval

One change to the rules themselves, one approval that an existing rule already requires, and
one re-classification resolved by ruling. None may be treated as incidental.

**Both open items were granted by the maintainer on 2026-09-19**, in the conversation that
resumed P9 after the Phase 1 `Call-ID` fix: *"我给你全权授权，你自己判断，执行到 phase2 结束"*
— full authority to judge and execute through the end of Phase 2. That grant is what items 1
and 2 below now rest on; they are recorded here as **approved**, not assumed, and neither may
be treated as incidental by a later agent.

1. **`AGENT.md` §2 scope change — APPROVED 2026-09-19.** *"No performance or capacity work …
   no benchmarking claims"* is relaxed to permit a capacity harness while **continuing to
   forbid published benchmark figures** (D10). The relaxation is scoped to P9.5 and P11 and
   does **not** license a calls-per-second or latency claim anywhere; D10 still governs.
2. **`AGENT.md` §14 rule 3 approval (no unconfirmed refactors) — APPROVED 2026-09-19.**
   Extracting the skeleton in P10 is a structural refactor, and that rule requires an explicit,
   approved plan **before any code moves**. The approval is for the extraction to be *planned
   and executed*; the plan itself is still written first, in P10, and reviewed before code
   moves — the approval waives the "do not start" gate, not the planning step.
3. **P6 → P8a promotion — never separately approved; resolved by ruling (2026-09-18).**
   P8a began as roadmap item P6, parked as *Optional/Pending*; no approved decision ever
   recorded its promotion to the Phase 2 work sequence or its framing here as a Phase 2
   "(blocker)". On 2026-09-18 the maintainer ruled that **P8a is a Phase 1 defect fix that
   closes P6**, not Phase 2 work. It was fixed on `fix/sippy-retransmission-timer`, merged
   into `main` (`d0d0501`) and released as **`v0.5.1`**. Recorded here so a future audit sees
   the re-classification was resolved by ruling, not left by omission.
