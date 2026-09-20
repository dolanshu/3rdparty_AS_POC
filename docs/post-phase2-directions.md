# Post-Phase-2 Directions — what comes after P11 and why

- **Status:** planning artefact, pre-decision
- **Date:** 2026-09-21
- **Owner:** project maintainer
- **Context:** Phase 2 (P8–P11) is complete. `phase2` branch carries P8 anti-fraud AS, P9 chained demo, P9.5 capacity probe, P10 platform extraction (`as_platform` library), and P11 TLS + Redis + capacity harness. Version on this repo is `0.9.0`; the library sibling at `../as_platform` is `0.2.0`. Nothing is merged into `main` and nothing is pushed.

## 1. How this document came to be

Phase 2's closing conversation asked two questions the repository had not yet answered in writing:

1. What is the CDR situation for a **third-party** AS (outside the operator IMS)? Does the AS need to generate one?
2. Beyond the session / context / load direction the maintainer proposed, what other directions exist after Phase 2?

The first question was answered by searching 3GPP TS 32.260 (IMS charging) and related material. The second was answered by surveying the feature lists of commercial and open-source SIP AS platforms (Kamailio, Sipwise NGCP, dSIPRouter, PortSIP UCaaS, 中兴 vIMS, Ericsson Cloud IMS, Nokia VoLTE core) and comparing them against this repository's registered production gaps.

This document records every serious candidate direction with its rationale so that a later conversation does not have to re-derive them.

## 2. Key finding — CDR is not a first-class direction for a third-party AS

The maintainer's intuition was correct: IMS charging trust is inside the core network. 3GPP TS 32.260 names **S-CSCF, P-CSCF, I-CSCF, BGCF, IBCF, and MGCF** as the standard CDR generators via Diameter Rf/Ro interfaces to the CCF (Charging Collection Function). The **home AS** (inside the operator IMS) can participate in online charging via Ro, but the **third-party AS** sits outside the S-SBC trust boundary. Operators do not use external AS records for billing.

What the third-party AS *does* generate that matters to someone is:

- **Usage records for its own operator** — "N calls today, M rejected by anti-fraud, K minutes of relay" — a reconciliation surface between the AS provider and the S-SBC operator, not a billing surface.
- These are a **natural byproduct** of a call session closing cleanly, not an independent direction.

Conclusion: CDR (as a standard charging direction) is **removed from the candidate list**. Usage records are folded into the Session Registry direction below.

## 3. The prerequisite — do this first

Nothing on the list below is credible until this is done.

### P0 — Publish `as_platform` library to a reachable remote (private is fine)

The `as_platform` library exists only at `/home/shudong/project/as_platform`. The application repository's CI workflow (`Makefile`, `.github/workflows/ci.yml`) clones it from `https://github.com/${{ github.repository_owner }}/as_platform.git`, which resolves to nothing. **CI cannot be green while the library is unreachable**, and P10/P11's "two repositories" claim is hollow while the library exists only on a local filesystem.

This is **not** a merge-into-main step — it is a publish step. The library repo needs any reachable remote (GitHub private, internal GitLab, even a bare git server); the application repo's CI clone URL then resolves, and `make check` runs against a real checkout. Until this is done, every subsequent direction inherits a kind-3 (CI) evidence gap that nothing else can close.

## 4. Depth directions — pick one to do completely

Each direction in this section is large enough to be a Phase 3 item on its own. They each have a beginning, middle, and end — a reviewer who sees the completed item can say "this project is genuinely capable in this dimension."

### D1 — STIR/SHAKEN (RFC 8224/8225) — identity verification on the originate side

**The story.** RFC 8688 (608 Rejected) says "an automated engine rejected this call." STIR/SHAKEN (RFC 8224/8225) says "the caller identity on this call was verified by an authoritative entity." They are complementary, not alternative. A reviewer who sees 608 without STIR will ask "but how do you know the suspect caller number is real?" A reviewer who sees both gets a complete anti-abuse story: the AS verifies the caller's identity before applying its reputation engine.

**Why now.** D5 explicitly deferred STIR/SHAKEN ("out of scope" — ADR-0007). The anti-fraud AS is its natural home — this is not platform-level, it is use-case-level. Regulators are mandating STIR/SHAKEN worldwide (FCC STIR/SHAKEN mandate in the US, Ofcom in the UK, CRTC in Canada). The `as_platform` library needs no changes; this is purely `src/anti_fraud_as/` work.

**Connection to existing work.** P11 already produces self-signed certificates for TLS termination; the same generation script pattern can produce STIR signing keys (Ed25519 JWK/JWS). P8's probe pattern (probe first, design after) applies: probe sippy's handling of the `Identity` header before committing to implementation.

**Engineering scope.** Medium. STIR signing is pure Python cryptography (Ed25519 + JOSE/JWS); the AS adds an `Identity` header to every outbound INVITE from the signing module, and verifies incoming `Identity` headers from trusted signers. sippy does not need core modification — it passes unknown headers through verbatim (verified in ADR-0007).

### D2 — HA Active-Standby with state replication

**The story.** "This AS can survive a process crash and keep serving live calls." Sipwise NGCP (Kamailio-based) emphasizes two-node active-standby with state replication; Kamailio's `syncer` module and `dispatcher` module are the canonical mechanisms; 中兴 vIMS lists "5-level disaster recovery, 99.999% reliability" as a headline feature.

**What Phase 2 already laid.** P11 gave us `RedisStateStore` for durability-after-restart. Session state that lives in Redis survives a restart. What is missing is: active-standby election (who is the primary), real-time state replication for in-flight calls (Redis Pub/Sub), and SIP OPTIONS keepalive so S-SBC knows to fail over.

**Engineering scope.** Large. State replication for *in-flight calls* (not just durability) is hard — it means every call state change has to be propagated to the standby, and the standby has to be able to take over at any point without dropping transactions. But the **display value is enormous**: a demo that kills the primary mid-call and the call continues on the standby is more convincing than any feature list.

### D3 — Session Registry + Call State Machine + Admission Control (maintainer's direction)

**The story.** This was the maintainer's own proposal before this document was written. Every call should be trackable in a **unified registry** that answers: how many calls are active right now, what state is each one in, which leg of which AS chain is it on, how long has it been there. And when active calls exceed a threshold, new calls get `603 Decline` with `Retry-After` instead of queuing indefinitely.

**Connection to existing work.** The gap is known: P9.5 found "no admission control — the 3-second wall-clock timeout is the only thing that turns a slow call into a failed one." P9 found "no cross-AS session key" — the fix is to use `P-Charging-Vector`'s ICID, which P9 measured is preserved end-to-end but nothing is keyed on it yet. P11's `RedisStateStore` is the natural registry backend (process-level for now, cross-process when needed). Session close naturally produces usage records for the AS's own operator (see CDR finding, §2).

**What this means for the platform.** `BaseCallController` moves from "create a controller, handle INVITE, dispose when done" to "register the call in a lifecycle-aware registry, drive it through explicit state transitions (`INIT → RECEIVED → DECIDING → ... → CLOSED`), and emit close events." This is a **platform library** change, not a use-case change — it improves every AS that uses `as_platform`.

**Engineering scope.** Medium. The state machine itself is conceptually simple; the work is in identifying the registry's lifecycle boundaries (what exactly gets created, what exactly gets torn down, and who tears it down — the controller? the stack? a watchdog timer?), and in the admission policy hook that the platform exposes and each AS overrides.

## 5. Breadth directions — pick one to lay wide

These directions do not deepen an existing narrative. Instead, they demonstrate that the `as_platform` abstraction is *not* just a refactoring of the two use cases that happened to exist. They add genuinely new dimensions the platform supports.

### B1 — Service Capability Exposure API (programmable platform)

**The story.** Every major IMS vendor (Nokia, ZTE, Ericsson) now emphasizes "open APIs" and "capability exposure" as the differentiator of a modern AS platform — not just SIP processing, but a programmable telecom service platform. A third party that cannot see or consume what the AS decided cannot integrate with it.

**Current state.** This repo has `GET /counters` and a rules edit API. `as_platform` exposes `internal_api` as a shell that each use case extends. But there is **no OpenAPI contract**, no versioning, no authentication on the API, and no callback/webhook mechanism for pushing verdicts out.

**What this would mean.** Add a new REST surface with a proper contract: `POST /api/v1/translate` (number translation test), `POST /api/v1/screen` (fraud verdict test), `GET /api/v1/sessions/{icid}` (session status by ICID — the cross-AS key from D3), `POST /api/v1/webhooks` (callback registration). Publish an OpenAPI spec. Add API key authentication.

**Engineering scope.** Medium. Extends `as_platform`'s `internal_api` shell with new contracts and security. The platform gains a genuinely new surface that neither Phase 2 use case explicitly designed for.

### B2 — Multi-tenancy

**The story.** One AS instance, multiple independent operators sharing it. Each tenant gets its own rules, its own anti-fraud blacklist, its own counters, and is completely isolated from the others. PortSIP UCaaS calls this "multi-tenant architecture for cloud deployment" and highlights it as "essential for cloud-native operations."

**Connection to existing work.** Nothing in the current codebase has a tenant concept. Session registry (D3) gets a tenant-ID dimension; `RedisStateStore` gets a per-tenant namespace; rules files and screening data get per-tenant directories; observability (counters, traces) get a tenant key.

**Engineering scope.** Medium-large. Multi-tenancy touches every subsystem — routing rules, screening data, state store, counters, internal API, and the console. It is the biggest breadth direction.

### B3 — RFC 3263 DNS SRV/NAPTR peer resolution

**The story.** The smallest direction in the list. Currently every peer address is a hard-coded `127.0.0.1:<port>`. Real SIP entities discover peer addresses via DNS SRV (e.g. `_sip._udp.as.example.com` resolves to `as1.example.com:5060` with priority/weight). This is already a registered production gap under Routing catalogue coupling and no operator would deploy an AS that cannot resolve its peers via DNS.

**Connection to existing work.** `NextHop.address` → `NextHop.resolved_addresses` (a list of `(host, port, priority, weight)` derived from SRV lookup), plus a 30-60 second cache to avoid hammering the resolver. dnspython is a standard dependency.

**Engineering scope.** Small. Quick win. A reviewer with telecom background will notice this was missing in Phase 2.

### B4 — A third AS use case (if it introduces genuinely new dimensions)

**The story.** The most direct way to prove P10's abstraction is not tailored to the two use cases that existed when it was written: build a third use case without modifying `as_platform`. **BUT** — D2 from Phase 2 plan is explicit: the selection criterion is **orthogonality**, not novelty. A third use case that covers the same dimensions (stateless · stateful · rewrite · reject) is isomorphic and proves nothing.

**What genuinely new dimensions would qualify?** A pre-pay AS (online balance check + Diameter Ro) introduces real-time external decision making and an online charging interaction. A multi-leg call forwarding AS (Call Forwarding Unconditional / Busy / No Answer) introduces per-destination routing logic and supplementary service handling. An emergency call routing AS introduces location-aware routing (PSAP) and regulatory logging requirements.

**Engineering scope.** Medium-large, and only worth it if the selected use case introduces genuinely new dimensions the existing two do not.

## 6. The ceremony cost — one or two items, not four or five

Every item in Phase 2 ran through the §5.1 pipeline (requirements → design → implementation → tests → acceptance), with an independent read-only review gate after each stage. This ceremony produces high-quality artefacts but it is **not cheap** — P10 alone had seven implementation steps, each with its own gate and findings.

The recommendation for Phase 3 is **one depth direction and optionally one breadth direction**, not more. Two complete items produce a coherent phase story; three shallow ones produce three half-finished ones.

## 7. What the plan says and why this document says more

`docs/phase2-plan.md` D10 explicitly selected TLS and the capacity harness as the two Phase 2 enhancement items. CDR was rejected in D10 with the note "it should be reconsidered at P10/P11, where 'what does every AS get for free' is exactly the question the platform must answer." This document is that reconsideration.

The D10 CDR note held under the assumption that CDR would be the platform's cross-cutting answer. The 3GPP finding in §2 changes that assumption — CDR is not the right cross-cutting answer for a third-party AS. But the *spirit* of D10 ("what does every AS get for free") still applies: session registry (D3), capability exposure (B1), and STIR/SHAKEN (D1) are all candidate cross-cutting answers that align with the third-party AS positioning.

Phase 2 plan D3 (the gap register is repositioned, not abandoned) also holds. The gaps registered in Phase 2 that the directions above close are:

| Registered gap | Closed by |
|----------------|-----------|
| Chain carries no shared call context beyond pass-through headers | D3 (Session Registry with ICID key) |
| Single process, no persistence → Restart safety, session recovery, watchdog | D2 (Active-Standby), D3 (Registry + dispose on close) |
| No admission control or back-pressure; fixed 3-second timeout is the only wall-clock boundary | D3 (Admission Control) |
| Peer addresses are 127.0.0.1 ports; no DNS/SRV resolution | B3 (DNS SRV/NAPTR) |
| No HA, no cluster, no active-standby | D2 |
| Rules drift between environments (two YAML files, differing only in addresses) | B2 (per-tenant isolation) |

## 8. Decision space — choose before this document ages

This document records the space of credible options. The maintainer must decide before merging `phase2` into `main`:

1. **P0 (library remote) — is this done or explicitly deferred?** It is a prerequisite for everything else.
2. **Depth direction — which one, and why?** D1 = identity + anti-abuse completeness; D2 = HA + telecom-grade reliability; D3 = session state + admission control. All three are defensible and each tells a different portfolio story.
3. **Breadth direction — optional, which one, and why?** B1 = platform programmability; B2 = multi-tenant deployment model; B3 = quick gap close; B4 = abstraction validation.
4. **Pipeline — keep the full §5.1 ceremony for Phase 3 items, or lighten it?**

Nothing in this document commits the repository to any direction — it only records the credible options, their trade-offs, and their connection to the existing work so a fresh conversation does not have to re-derive them.
