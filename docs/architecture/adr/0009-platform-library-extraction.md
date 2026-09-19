# ADR-0009: Platform extraction — the `as-platform` library, its seams and how this repository consumes it

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** project maintainer
- **Related:** `docs/phase2-plan.md` section 2 (D8, D9, D10) and section 3 (P10), section 5.1,
  section 8 item 2 · `docs/requirements/functional-and-nonfunctional.md`
  (REQ-F-029…REQ-F-033, REQ-NF-019…REQ-NF-021) · ADR-0001 (sippy) · ADR-0002 (process
  separation) · ADR-0007 (decision 9 — a second process, not a framework) · ADR-0008
  (decision 7 — the chain is P10's input) · `docs/architecture/hld.md` sections 8 and 10 ·
  `docs/architecture/lld.md` section 2.3, section 9.1, section 9.6, section 10.5,
  section 11 ·
  `AGENT.md` sections 4.1, 4.3, 10, 12, 14 rule 3

## Context

`docs/phase2-plan.md` D8 splits the repository in two stages. Stage one put the anti-fraud AS
**in this repository** (P8), so the second use case could reuse the mock, the console, the
three-layer test scaffolding and the document set. Stage two extracts the **skeleton shared
by the two AS instances** into a library in a **new repository**, after which this repository
becomes the library's **reference implementation and first user**. P10 is that second stage.

It has three inputs already on record and does not re-litigate them: the pluggable state
store (D9 — an external store is the production answer, deferred to P11), the friction the
chained demo surfaced (`REQ-NF-018`, P9), and the capacity/back-pressure constraints (D10,
P9.5). What the chain added to the argument is in ADR-0008 decision 7: the two instances
configure their next hop in two different ways, the routing catalogue couples a dial plan to
a peer inventory, and **the same omission — a controller that forgot to regenerate the
outbound dialog `Call-ID` — was made twice**. A mistake made twice in copied code is the
strongest single argument that the copy, not the mistake, is the defect.

Four questions had to be settled before any code moves:

1. **What is a library here, and to what standard?** D8 says the new repository must not copy
   this repository's ~24-document application set, and must not ship nothing either.
2. **What exactly moves, and what stays use-case-specific?** The boundary is described in
   `docs/architecture/lld.md` section 9.1 ("What is shared" / "What deliberately stays
   use-case-specific"), but a description of *sharing by direct import* is not a module split;
   the two are not the same list.
3. **How does the extracted shell take a decision from an application?** The two controllers
   are of comparable size (about a thousand lines each), near-verbatim in the relay mechanics
   and different only in the decision and its vocabulary. The interface between them is the
   thing P10 exists to design (ADR-0007 decision 9).
4. **How does this repository consume the library, and what does that cost the clean-checkout
   guarantee?** `AGENT.md` section 10 puts *"clone → `uv sync` → `make demo`"* above feature
   work. A second repository changes that sentence, so the mechanism and its exact behaviour
   have to be measured, not assumed (`AGENT.md` section 6).

## Decision

### 1. A library, in its own repository, on the library standard of D8

**The new repository is `as_platform`, checked out beside this one (`../as_platform`), and it
is a library, not a service.** Its distribution name is `as-platform` (PEP 503 normalisation
of the import package `as_platform`); its import package is `as_platform`. It follows the
**library standard of D8, not `AGENT.md` section 4.1's application layout**: there is no
`config/`, `deploy/`, `tools/` or `console/`, and the operations set (`deployment` /
`runbook` / `troubleshooting`) does not apply to it. It carries instead an **API reference**,
an **integration guide** and a **compatibility matrix** (REQ-NF-019), plus the meta files a
distributable needs — `pyproject.toml`, `VERSION`, `CHANGELOG.md`, `README.md`, `LICENSE`, a
`Makefile` gate and CI (REQ-NF-021).

**It is a separate repository, not a uv workspace monorepo** (REQ-NF-019). This repository
consumes it through a `path` source (decision 6), not by workspace membership: neither
`pyproject.toml` declares the other as a `[tool.uv.workspace]` member, and each keeps its own
lockfile and its own gate. A workspace would couple the two lockfiles and contradict the
"two repositories, two gates" split that D8 and REQ-NF-021 require.

**The library is typed, and `py.typed` is load-bearing.** Without it `mypy` refuses the
import and this repository's `make lint` fails (*Verified facts*, (e)). It is a library
artefact, not an optional nicety.

**One sippy.** The library depends on the same pinned stack as this repository
(`sippy==2.4.2`, Python 3.10), because the sippy adapter boundary moves into it. It must not
widen that pin: two sippy versions in one interpreter would break the in-process tests
(`docs/architecture/lld.md` section 5).

### 2. The module split: the skeleton moves, the use cases stay, two surfaces keep a thin facade

**What moves into `as_platform`** — the parts LLD section 9.1 calls use-case-agnostic, plus
the shells the two applications currently duplicate:

| Library module | Moved from | Responsibility |
| --- | --- | --- |
| `observability/` | `as_app.observability` | structured logging, counters/dispositions/peer status, per-Call-ID trace and console feed |
| `sip_adapter` | `as_app.sip_adapter` | `PASSTHROUGH_HEADERS`, `B2BUA_CALL_ID_SUFFIX`, `outbound_call_id`, `extract_called_number`, `is_allowed_peer`, `cancel_transaction_timers`, `CallLeg` (`TrunkMessage` is not carried — deleted with the move, below) |
| `hop` | `as_app.routing.rules` | the `NextHop` value object — the ordered next hop a B2BUA relays towards (its own module, below) |
| `errors` (mechanism) | `as_app.errors` | the memberless `ErrorCode` base, `SIP_PHRASES`, `sip_status_for`, `AsError` (decision 3) |
| `bootstrap` (plumbing) | `as_app.bootstrap` | `ShutdownController`, `install_signal_handlers`, `check_port_available` |
| `version` | `as_app.__init__` | the distribution → `VERSION` chain |
| `internal_api` (shell) | both `internal_api.py` | the app factory, `InternalApiServer` and the payload builders, generalised over a payload provider instead of bound to a `RuleSetStore` |
| `call_controller` (shell) | both `call_controller.py` | `BaseCallController`, `BaseCallMap`, `PolicyDecision` (decision 4) |
| `main` (shell) | both `main.py` | `BaseAsStack` |
| new | — | `Transport` / `UdpTransport` and `StateStore` / `InMemoryStateStore` (decision 5), and `py.typed` |

**What stays in this repository** — the use cases and everything that is this repository's
identity:

- `as_app/`: `routing/` (`rules.py` — the document model, `RuleSet` and `RuleSetStore`, plus a
  re-export facade for `NextHop`; `engine.py` — the translation), `errors.py` (the RULE/ROUTE
  codes), `call_controller.py` (`CallController`), `main.py` (`AsStack`), `bootstrap.py`
  (`AsSettings` and the self-check), `internal_api.py` (routes and bindings),
  `sip_adapter.py` (facade).
- `anti_fraud_as/`: `screening.py`, `caller_state.py`, `screening_data.py`, `errors.py` (the
  FRAUD codes, decision 3), `call_controller.py` (`FraudCallController`), `main.py`
  (`FraudAsStack`), `bootstrap.py`, `internal_api.py`.
- `console/`, `s_sbc_mock/`, `tools/`, `tests/`, `config/`, `deploy/` — unchanged. The
  library carries **no mock and no console**: a library-only consumer brings its own trunk
  peer, which is the same "we implement the external AS" boundary as `AGENT.md` section 1.

**Two surfaces keep a thin re-export facade in `as_app`.** `as_app.sip_adapter` and
`as_app.observability.*` are referenced **by path** in `tools/`, in `tests/`, and in the
frozen ADRs and LLD. The implementation moves to the library; the modules stay as re-export
facades so those references keep resolving and the three-layer suite stays the unchanged
anti-regression guard of REQ-F-031. A facade adds no behaviour and no state, and it is a
permanent part of the design, not a migration shim.

**`NextHop` moves into the library, and `as_app.routing.rules` re-exports it.** The base
controller walks a hop's `name` / `address` / `port`, `sip_adapter.build_request_uri(number,
hop)` is typed on `NextHop`, and `PolicyDecision.next_hops` is an ordered `NextHop` list — so
the moving skeleton needs the *hop value object*, and if it stayed in `routing/` the library
would have to import `as_app.routing.rules` and **REQ-F-030 would fail**. `NextHop` therefore
gets its **own module** in the library — `as_platform/hop.py` — precisely so `sip_adapter` and
`call_controller` can both import it without a cycle; **the owning module is stated, not left
to the implementer**. `src/as_app/routing/rules.py` imports it from the library and
**re-exports** it, so `as_app.routing.rules.NextHop` stays importable — `tests/`, `tools/` and
the frozen ADRs and LLD reference it by that path — and the routing YAML schema is unchanged.
This is the **same facade pattern** decision 2 already uses for `as_app.sip_adapter` and
`as_app.observability.*`, and it is the third such facade.

**Why `NextHop` is skeleton and not number-translation-specific.** A B2BUA always relays
towards an ordered list of next hops, so the *hop value object* is skeleton. What is
use-case-specific is the **catalogue that produces the list** — `routing/rules.py`'s document,
schema, `RuleSet` and `RuleSetStore`, and `routing/engine.py`'s translation — and those stay
in this repository. `NextHop.transport` stays `Literal["udp"]` in P10 (REQ-NF-020); P11 widens
it when it adds TLS.

**`extract_called_number` keeps its name.** LLD section 9.1 records that the name is wrong
for the anti-fraud caller (it parses a URI user part). Renaming it during the move would
touch both applications and is a drive-by change (`AGENT.md` section 14 rule 4); the naming
debt is recorded, not fixed.

**`TrunkMessage` is not carried into the library; it is deleted with the move.** LLD
section 9.1 records that it is never populated and never used, and it is provably dead:
exactly two references exist in the whole repository, both inside its own module —
`src/as_app/sip_adapter.py:41` (its `__all__` entry) and `src/as_app/sip_adapter.py:122`
(the class). **The maintainer's ruling (2026-09-19): carrying known-dead code into a
brand-new artefact is the wrong default, and removing it is behaviour-neutral.** The deletion
is performed as part of the move, not as a drive-by change (`AGENT.md` section 14 rule 4),
and the `__all__` entry is removed with it. LLD section 9.1's friction note records that P10
removed it rather than inherited it.

### 3. The error model is split by family over one mechanism, and the `REQ-F-023` delta is recorded in the traceability note

**One mechanism, per-family code sets.** Python forbids subclassing an `Enum` that has
members, so a single `AsErrorCode` cannot be extended by the library and the applications.
The library therefore owns the **memberless** base and the mechanism:

```text
as_platform/errors.py
    ErrorCode(Enum)                  # no members; __init__(code, sip_status, message)
    SIP_PHRASES: Final[dict[int, str]]
    sip_status_for(code: ErrorCode) -> int
    AsError(Exception)               # typed on ErrorCode, so it carries any family
```

Each family is a subclass in the package that owns the vocabulary:

| Family | Enum | Home | Codes |
| --- | --- | --- | --- |
| skeleton | `SkeletonErrorCode(ErrorCode)` | `as_platform` | `AS-CFG-*`, `AS-PEER-*`, `AS-INT-*` |
| number translation | `AsErrorCode(ErrorCode)` | `src/as_app/errors.py` | `AS-RULE-*`, `AS-ROUTE-*` |
| anti-fraud | `FraudErrorCode(ErrorCode)` | `src/anti_fraud_as/errors.py` | `AS-FRAUD-*` |

**Every code, SIP status and log message stays byte-identical**, so REQ-F-031's "the same
`AS-*` error codes" holds and no wire behaviour moves. `SIP_PHRASES` (including
`608: "Rejected"`) moves once, so the phrase cannot drift between families.

**The `REQ-F-023` delta — the requirement is not reworded; the traceability note carries it.**
That row — written for P8 — says the `AS-FRAUD-*` codes are added to *"the authoritative model
in `src/as_app/errors.py`"*. After the split the **mechanism** is the library's and the
`AS-FRAUD-*` family lives in `src/anti_fraud_as/errors.py`; `src/as_app/errors.py` holds only
the translation families plus the facade re-exports. The requirement's *intent* — one model, no
second error vocabulary, codes mapped to SIP status and log message — is preserved and is in
fact enforced by the shared base; its *location* is not. **The maintainer's ruling
(2026-09-19): the requirement's text stays exactly as it is** — it was true when written, and a
stage may not reword a frozen requirement (plan section 5.2). The delta is recorded where this
repository already records such deltas: in the SRS **traceability note**, exactly as P8a
handles `REQ-F-011` (its text is unchanged and the note carries the change). That note records
that after P10 the authoritative *model* is the library's mechanism, that the `AS-FRAUD-*`
family lives in `src/anti_fraud_as/errors.py`, and that every code, status and message is
unchanged. **`AGENT.md` section 4.3 is different**: it is a structural document, not a frozen
requirement, and `AGENT.md` section 13 requires structural changes to update it — so section
4.3 is updated **in the implementation commit** to name the library mechanism and the three
families.

**The one bounded class of test edit — accepted, enumerated and recorded.** The extraction's
anti-regression promise is that this repository's suite does not change (REQ-F-031). One class
of unit test is a **bounded exception**, and it is stated precisely rather than as "an import
line":

> The permitted class of test change is **"repoint a read, an iteration or a type annotation
> of a moved enum member at the family enum that now owns it"**. No assertion's expected value
> changes; no test is deleted, weakened or added. The single assertion whose *scope* changes is
> the uniqueness/status-coverage test, which is **strengthened** to cover all three families.

The sites are known, not hypothetical (verified against `dc1ab18`). The implementation stage
repoints every site whose member genuinely moved — a grep of `tests/` for `AsErrorCode` finds
them all — and reports the complete list in the acceptance evidence:

| Test | Site | Why it is repointed |
| --- | --- | --- |
| `tests/unit/test_errors.py::test_every_code_has_a_unique_identifier_and_status` | `:28-31` | iterates `AsErrorCode` to assert codes are unique and every status has a phrase; after the split it must assert this **across all three families** — the one test whose *scope* is **strengthened**, not merely repointed |
| `tests/unit/test_errors.py::test_relevant_sip_statuses_are_present` | `:36-37` | asserts `{404, 603, 403, 500}` is a subset; `403` is `AS-PEER-001`, now a `SkeletonErrorCode`, so the read moves |
| `tests/unit/test_fraud_error_model.py::test_the_fraud_codes_are_unique_and_prefixed` | `:112` | derives the fraud list by iterating `AsErrorCode`; iterates `FraudErrorCode` |
| `tests/unit/test_fraud_error_model.py::test_fraud_codes_live_in_the_shared_error_model` | `:133-134` | asserts `call_controller.AsErrorCode is AsErrorCode` and `screening_data.AsErrorCode is AsErrorCode`; becomes `FraudErrorCode`. The assertion's **intent** — one authoritative model, no private per-process vocabulary (REQ-F-023) — is preserved and still asserted |
| `tests/unit/test_fraud_error_model.py::test_the_configuration_failures_are_answered_with_500` | `:101` | parametrised over `AsErrorCode` with FRAUD codes; the annotation repoints |

**Implementation-stage finding (2026-09-19, step 1): a sixth site, in a second bounded class.**
Step 1's mandatory `as-platform` entry in `[project].dependencies` (decision 6) collides with
`tests/unit/test_fraud_configuration.py::test_the_runtime_dependency_pin_is_unchanged`, which
asserted the literal substring `dependencies = ["sippy==2.4.2"]` and so could not survive that
entry — `[project].dependencies` is one TOML array, and the enumeration above missed this site.
**The second permitted class is narrower than the first and can only strengthen it:** a
structural assertion that pins the **literal text of a file the extraction is required to
change** is repointed at the **same fact expressed structurally**, and may only be
**strengthened**, never weakened. The sippy pin is still asserted unchanged — `sippy==2.4.2`
remains an entry, per `AGENT.md` section 6 — and the exact set of `[project].dependencies`
entries is now pinned rather than left open. The assertion's expected *fact* is unchanged; no
test is added, deleted or weakened.

This is the one place where the literal sentence *"If that suite has to change to accommodate
the extraction, the extraction is wrong, not the tests"* (requirements traceability note) meets
the split; the note is **qualified in place** so it keeps its force — the extraction may not
change what a test *asserts* — while naming this bounded exception. **The maintainer's ruling
(2026-09-19): the bounded edit is accepted and recorded.** `REQ-F-031`'s promise is that the
three layers **stay green**, which holds — it is not a promise that no test file's read,
iteration or annotation ever changes. This is the only class of test change the extraction is
allowed to make.

### 4. The controller seam: the base owns the relay, the application owns the decision, `PolicyDecision` is the one value between them

**The library owns the relay mechanics both controllers duplicate; the application owns the
decision.** The seam keeps the name `apply_call_policy`, because the LLD calls it "the single
seam" and every call site uses that name. The base implements it and calls one application
hook:

```text
BaseCallController.apply_call_policy(event)   # library: relay, failover, timers, trace, log
        -> self.decide(event)                 # application: the only override
        -> PolicyDecision
```

`PolicyDecision` is **plain data**, so the base can apply a decision without knowing either
use case's vocabulary:

| Field | Meaning |
| --- | --- |
| `action` | `PolicyAction.RELAY` or `PolicyAction.REJECT` |
| `outbound_event` | relay path: the `CCEventTry` to originate (already rewritten, or the original for a pass-through) |
| `next_hops` | relay path: ordered `NextHop` list; empty means no failover |
| `error` | reject path: the `AsError` carrying the family code, its SIP status and its phrase |
| `disposition` | the `CallDisposition` to record, supplied rather than derived (LLD section 9.6) |
| `attributes` | extra **trace** fields for this decision (for example `leg`, `error_code`, `rule_id`) |
| `reject_trace_summary` | reject path: the trace summary string — *"…relayed to the trunk leg"* for the translation AS, *"…answered on the trunk leg"* for the anti-fraud |
| `reject_log_message` | reject path: the log message — *"call rejected by routing policy"* vs *"call rejected by screening"* |
| `reject_log_fields` | reject path: the extra **log** fields beside `error.as_log_fields()` — the translation AS contributes `rule_id`; the anti-fraud contributes `screen_source`, `list_entry`, `sip_608_declared` |
| `relay_log_message` | relay path: the originate log message — *"invite originated towards the next hop"* vs *"invite relayed towards the next hop"* |
| `relay_log_fields` | relay path: the extra **log** fields — the anti-fraud contributes `verdict=ScreeningVerdict.ALLOW.value` |

**Those string fields exist so the two applications' current trace and log lines are
reproduced exactly, byte for byte — that is what REQ-F-031 requires.** This is the one place
the design has to carry per-application **strings**, and it is preferable to branching on
"which application am I" (which the design forbids): the base owns the *mechanism* — when to
emit, at which level, on which leg — and the application supplies the *vocabulary* as data,
exactly as it already supplies the error code and the disposition.

The two applications become subclasses:

- `CallController.decide()` calls `routing.engine.decide`, rewrites the called number and
  returns `RELAY` with the translated event, the rule's hops and `rule_id`.
- `FraudCallController.decide()` calls `CallerStateStore.observe` then `screening.screen` and
  returns `REJECT` with the `FraudErrorCode` error and `screen_source` / `list_entry` /
  `sip_608_declared`, or `RELAY` with the unchanged event and its single configured hop.

**The peer-status key is an overridable point on the base.** The default renders
`name:address:port` (the translation AS's `_next_hop_peer`); the anti-fraud **overrides** it to
render `address:port`, with the `"-"` fallback when no hop is configured. The anti-fraud's
single hop therefore needs a `NextHop` whose `name` is **never rendered** — it is
`fraud_sbc_peer` (the `FRAUD_SBC_PEER_*` knob) — so its key is unchanged.

**The base stores the serving hop as a `NextHop`, while `uaO` still receives the
`(address, port)` tuple.** `build_request_uri` and the default peer key need the value object;
the outbound `UA` is constructed with `(hop.address, hop.port)`, so `UA(..., nh_address=...)`
is unchanged and the anti-fraud's tuple form is preserved at the sippy boundary.

**The one behavioural difference is reconciled by the base owning the full version.**
`CallController._relay_from_next_hop` walks a failover list; `FraudCallController`'s has no
failover path. The base implements the failover version, and the anti-fraud's `next_hops` is
a one-element list, which reproduces its current behaviour exactly — there is no branch on
"which application am I".

**`BaseCallMap` and `BaseAsStack` carry the process shell.** `BaseCallMap` enforces the peer
allowlist and creates one controller per INVITE (LLD section 9.2); `BaseAsStack` owns
`SipConf` identity pinning, the `SipTransactionManager`, the `ED2` loop, the loop-owned
shutdown/reload timers and the stop ordering of LLD section 9.7. The `Base` prefix is
deliberate: it avoids shadowing the applications' public `AsStack` / `FraudAsStack`, which
`tools/` and `tests/` import by name.

**The one-leg relaxation is a base invariant, not an anti-fraud special case.** LLD
section 9.6 requires that `uaO` may stay `None` for a call's whole lifetime, that a reject
needs no `RoutingDecision`, that the disposition is supplied, and that `dispose()` guards
`None`. All four move into the base as stated invariants, because the number-translation AS
already tolerates them on its error branches.

### 5. The two pluggable seams are interfaces with one implementation each — P11 builds the second

**P10 defines the boundaries and stops there** (REQ-NF-020, D9, D10). The library exposes two
interfaces and ships exactly one implementation of each:

| Seam | Interface | P10 implementation | P11 second implementation |
| --- | --- | --- | --- |
| transport | `Transport` | `UdpTransport` (the existing behaviour) | TLS |
| state store | `StateStore` | `InMemoryStateStore` | Redis |

**No second implementation is written, no external service is added, and no load harness is
built.** The in-memory cross-call state (REQ-NF-012) remains the only store, and `make demo`
keeps running fully offline with no container. The capacity harness is a P11 capability (D10)
and is **not** a seam: it is a capability, not a swappable dimension.

**The state-store seam does not move the anti-fraud's ownership boundary.** `CallerStateStore`
— the call-rate window and the reputation ledger — stays in `src/anti_fraud_as/` and stays
**process-level, never in the per-call controller** (D9, LLD section 9.2). The seam is the
storage underneath it; putting the window itself behind the seam, or on the controller, is
the silent failure D9 names. The transport seam is used by the stack's socket binding, not by
the controller.

**`AGENT.md` section 12 is the reason this is a boundary and not a framework.** Two
implementations do not exist yet, so a registry, a plugin protocol or a factory that selects
an implementation would be premature abstraction. The library ships one class per seam and
the interface it satisfies; P11 adds the second class and, only then, the selection.

### 6. This repository consumes the library through a `path` source with `editable = true`

**The mechanism.** `pyproject.toml` gains the dependency and the source:

```toml
[project]
dependencies = ["as-platform", ...]

[tool.uv.sources]
as-platform = { path = "../as_platform", editable = true }
```

`editable = true` is required, not cosmetic: during the staged extraction (decision 7) a step
edits the library and immediately runs this repository's gate against it, and an editable
install links the checkout instead of copying it.

**The behaviour was measured, not assumed** — the facts are in *Verified facts* below. Four
of them shape the decision:

1. **The source is mandatory.** A dependency key alone does not resolve: `uv sync` fails with
   *"as-platform was not found in the package registry"*. There is no fallback to a registry.
2. **The default is a copy, not a link.** A `path` source with no `editable` key installs a
   **non-editable** copy (`direct_url.json` → `{"dir_info":{"editable":false}}`);
   `editable = false` is the explicit spelling of the same thing. Only `editable = true`
   links the checkout.
3. **A version constraint in `dependencies` is ignored.** `as-platform>=99.0` against a
   `0.4.0` checkout installed `0.4.0` and exited `0`. The pin is not a guard.
4. **With a `path` source the lockfile cannot constrain the library's version either.**
   `uv sync --locked` refuses when the library's version changed (*"The lockfile at `uv.lock`
   needs to be updated, but `--locked` was provided"*), but `uv sync --frozen` accepted the
   same skew, installed the new version silently, and left the lock recording the old one. A
   `path` dependency has no version to resolve against, so neither the pin nor the lock is a
   version guard.

**The honest position on the guard, because ADR-0009 measured the opposite of what an earlier
draft concluded.** With a `path` source the lockfile **cannot constrain the library's
version**: a constraint in `[project.dependencies]` is silently ignored (fact 3) and
`--frozen` accepts a skew (fact 4). Therefore **the lock is not what catches a library move**,
and `.github/workflows/ci.yml`'s comment that every job runs `uv sync --frozen`, "which fails
when …", is true for **registry** dependencies and **not** for this path dependency. Every CI
job needs a **second checkout** of the sibling library repository or it fails with
`Distribution not found at: file:///…` (LLD section 11.6's structural list already records
that checkout; the two are now consistent and explicit). What actually catches a skew is a
**gate**, not a lock: the library carries its own `ruff` / `mypy` / `pytest` gate (REQ-NF-021)
and this repository's gates run against whatever sibling checkout is present, so a skew shows
up as a **gate failure**, not a lock failure. The residual — no versioned consumption, so
nothing enforces the compatibility matrix at install time — is an **accepted gap** of the
chosen mechanism, entered in `docs/production-gaps.md` in the implementation commit. A real
deployment would consume a published wheel or a pinned VCS source; this POC cannot, because
the library has no remote and pushing is out of scope.

**`py.typed` is now a hard requirement of this repository's gate** (*Verified facts*, (e)):
without it `mypy` reports `import-untyped` and `make lint` fails.

**The `path` is relative to the consuming `pyproject.toml`.** `../as_platform` therefore
means a sibling of this repository's root — the layout REQ-F-032 names — and a consumer
nested one level deeper does not find it (measured, *Verified facts*, (f)). That is what
makes the guarantee "clone **both** repositories side by side" exact rather than vague.

### 7. The extraction is staged, and every step leaves this repository demonstrable

**Seven steps, each of which leaves `make lint` clean and all three layers green**
(REQ-F-033, D7, `AGENT.md` section 10). A step that would leave the repository broken is not
a valid step, and no step is allowed to be "temporarily red".

| # | Step | Leaves the repo |
| --- | --- | --- |
| 1 | Create the library repository and add the `path` dependency (decision 6). No code moves. | building; the dependency resolves and is unused |
| 2 | Move the leaf modules — `observability/`, the `errors` mechanism plus the skeleton family, `sip_adapter` — with the `as_app` facades (decision 2). | green; the facades keep every by-path reference resolving |
| 3 | Move the version chain and the `bootstrap` plumbing; generalise `check_port_available` / `ShutdownController` / `install_signal_handlers`. | green |
| 4 | Move the controller shell: `BaseCallController` + `PolicyDecision` + `BaseCallMap`, then rewire both controllers to `decide()` and preserve the public `AsStack` / `FraudAsStack` names (decision 4). | green; the largest step, and the one the three layers guard |
| 5 | Move and generalise `internal_api` (a payload provider instead of a bound store); both applications keep their routes and payload shapes. | green |
| 6 | Add the two seams: `Transport` / `UdpTransport` and `StateStore` / `InMemoryStateStore` (decision 5), one implementation each. | green; no behaviour change |
| 7 | Give the library its own suite and gate, its independence assertion and its documents (decisions 1 and 8). | green; the library is independently verifiable |

**The order is by dependency, not by size.** The leaf modules have no dependency on the
controller; the controller shell depends on `errors`, `sip_adapter` and `observability`; the
stack depends on the controller and `internal_api`; the seams are last because they are new
code and cannot be validated by the existing suite until it is green again. Step 4 is the
only step that can change behaviour, and it is guarded by the full three layers plus the
committed probe `tools/chained_as_probe.py` — which is exactly why it is not step 1.

### 8. `AGENT.md` section 10 is restated, not weakened — and the library carries its own gate

**The guarantee changes from "clone → `uv sync` → `make demo`" to "clone both repositories
side by side → `uv sync` → `make demo`".** REQ-F-032 records this as an **explicit
exception**, so a later reader does not read the weaker sentence as a defect. The
implementation commit updates `AGENT.md` section 10, `README.md` and `docs/README.md` in the
same commit (`AGENT.md` sections 12 and 13), and the `docs/README.md` repository tour names
the second checkout.

**The library's gate does not replace this repository's.** REQ-NF-021 gives the library its
own `ruff` / `mypy` / `pytest` gate, so a change to the library is verifiable where the
library lives. This repository's three layers remain the **application's** gate (`AGENT.md`
section 11); the two are different evidence, and neither substitutes for the other.

## Verified facts (measured on this machine, 2026-09-19)

`AGENT.md` section 6: `uv` behaviour is observed, never assumed. The consumption mechanism of
decision 6 was settled by a **scratch probe** under `/tmp/p10probe` — a throwaway library
(`as_platform`, `VERSION` 0.4.0) and seven consumer variants (six top-level, one nested), each
varying one key of `pyproject.toml`. That scratch form is not committed; **its reproducible
form is `tools/path_dependency_probe.py`**, which rebuilds the same layout in a temporary
directory and re-measures every fact below, exiting non-zero when any expectation does not
hold (the P9.5 probe's guard is the precedent). Run it with `uv run python
tools/path_dependency_probe.py`; the recorded output below is from the run that closed this
stage. Tool versions: `uv 0.12.15`, CPython `3.10.12`.

**(a) A dependency key with no `[tool.uv.sources]` entry does not resolve.**

```text
$ uv sync          # dependencies = ["as-platform"], no path source
error: No solution found when resolving dependencies
  cause: Because as-platform was not found in the package registry and your project depends
         on as-platform, we can conclude that your project's requirements are unsatisfiable.
```

**(b) A `path` source installs a copy by default; `editable = true` links the checkout.**

```text
source                              direct_url.json                       site-packages
path = { path = "../as_platform" }   {"dir_info": {"editable": false}}    as_platform/ (copy)
path = { ..., editable = false }     {"dir_info": {"editable": false}}    as_platform/ (copy)
path = { ..., editable = true }      {"dir_info": {"editable": true}}     _editable_impl_as_platform.pth
```

**(c) A version constraint in `dependencies` is ignored for a path source.**

```text
$ uv sync          # dependencies = ["as-platform>=99.0"], path source, editable = true
 + as-platform==0.4.0 (from file:///tmp/p10probe/as_platform)     # exit 0; the pin is ignored
```

**(d) `--locked` refuses a stale lock; `--frozen` accepts the same skew and does not update
the lock.** With the library bumped `0.4.0` → `0.5.0` and a lock recording `0.4.0`:

```text
$ uv sync --locked
error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.

$ uv sync --frozen
 - as-platform==0.4.0 (from file:///tmp/p10probe/as_platform)
 + as-platform==0.5.0 (from file:///tmp/p10probe/as_platform)     # accepted silently; uv.lock still records 0.4.0
```

**(e) `py.typed` is required or `mypy` refuses the import.**

```text
# without src/as_platform/py.typed
src/consumer/app.py:3: error: Skipping analyzing "as_platform": module is installed, but
    missing library stubs or py.typed marker  [import-untyped]

# with it
Success: no issues found in 2 source files
```

**(f) The `path` is resolved relative to the consuming `pyproject.toml`.** A consumer at
`nested/a/consumer3` with `path = "../as_platform"` fails with *`Distribution not found at:
file:///tmp/p10probe/nested/a/as_platform`*, which is what fixes the "side by side" layout of
decision 6.

**(g) The key may be spelled either way.** `as_platform` and `as-platform` both resolved to
the same distribution (PEP 503 normalisation); one probe variant used the underscore in both
`[project]` and `[tool.uv.sources]` and it worked.

**Conclusion.** The `path` + `editable = true` mechanism works and is the right one for the
staged extraction, and four of its properties are **not** what a reader would assume: the
default is a copy, the version pin is ignored, `--frozen` accepts a version skew (so the lock
is not a version guard), and the import needs `py.typed`. Each is now a stated property of
decision 6 rather than a surprise in the implementation stage.

**What the probe does not prove.** It measures `uv`'s resolution and install behaviour against
a two-module stand-in library, not the real skeleton, so it says nothing about the extraction
itself or about the runtime of the extracted code — that is what this repository's three
layers and the committed probes are for. `tools/path_dependency_probe.py` reproduces exactly
this scope and no more.

## Consequences

- **Two repositories to clone.** The clean-checkout guarantee of `AGENT.md` section 10 is
  restated as "clone both side by side" (decision 8, REQ-F-032). A checkout with only this
  repository does not resolve `as-platform` at all (*Verified facts*, (a)).
- **The library version is not a compatibility guard, and the lock does not supply one.** A
  `path` source ignores the version constraint in `dependencies` (*Verified facts*, (c)) and
  `--frozen` accepts a version skew (*Verified facts*, (d)), so neither the pin nor the lock
  constrains the library. The contract is the **compatibility matrix** (REQ-NF-019), enforced
  by the library's own gate and this repository's gates running against the sibling checkout —
  a gate failure, not a lock failure (decision 6).
- **`py.typed` is a hard requirement.** Without it this repository's `make lint` fails, so it
  is part of the library's definition of done, not a later addition.
- **The error model is one mechanism with three code sets** (decision 3). `REQ-F-023`'s text is
  **not reworded**; the delta is recorded in the SRS traceability note, and `AGENT.md` section
  4.3 is updated in the implementation commit.
- **The three-layer suite is the anti-regression guard.** The only class of test change the
  extraction forces is the bounded repoint of decision 3 — a read, an iteration or a type
  annotation of a genuinely moved enum member, accepted by the maintainer on 2026-09-19 and
  the only class the extraction is allowed to make. No assertion's expected value changes; the
  one uniqueness/status-coverage test is **strengthened** in scope (REQ-F-031).
- **The reference implementation has an update obligation.** When the library changes, this
  repository follows in the same piece of work: it is the first user, not a consumer at a
  distance (D8).
- **P11 receives interfaces, not implementations** (decision 5). It adds TLS and Redis behind
  seams that already exist, which is what makes its "second implementation" claim meaningful.
- **The facades are permanent** (decision 2). `tools/` and `tests/` keep importing
  `as_app.sip_adapter` and `as_app.observability`, so the re-export modules stay for the
  repository's lifetime, not just for the migration.

## Gaps accepted

- **No versioned consumption, and no lockfile constraint either.** The library is consumed
  from a filesystem path, not a registry, so there is no version resolution, no pin
  enforcement (*Verified facts*, (c)), no lockfile constraint (*Verified facts*, (d)) and no
  way for a third party to consume it without the checkout. Production: publish the library
  and consume it by version, keeping the compatibility matrix as the contract.
- **The interface is induced from two instances.** The extraction has exactly two samples
  (D2, ADR-0007 decision 9), so `PolicyDecision`, `Transport` and `StateStore` are shaped by
  them. A third use case may show a dimension neither has; the seams are the mitigation, not
  a proof.
- **No second transport, no external state store, no capacity harness** (decision 5,
  REQ-NF-020). They are P11's, and building them now would remove a reason P11 exists (D9).
- **The library carries no mock S-SBC and no console.** A library-only consumer brings its
  own trunk peer and its own UI; the mock and the console stay in this repository.
- **`extract_called_number` keeps a name that is wrong for one caller** (decision 2, LLD
  section 9.1). The naming debt is recorded, not fixed; renaming it is a separate, approved
  change. The unused `TrunkMessage` is **not** carried: it is deleted with the move
  (decision 2).
- **The library's gate does not run in this repository's CI.** A library change can pass here
  while failing the library's own gate until the library's CI is wired (decision 8).
- **`REQ-F-023`'s text names a location the split moves** (decision 3). The requirement is
  **not reworded** — the delta is recorded in the SRS traceability note, and `AGENT.md` section
  4.3 is updated in the implementation commit.
- **The probe's measurements are only as good as its stand-in.** It measures `uv`'s resolution
  and install behaviour against a two-module stand-in library, not the real skeleton, so it
  says nothing about the extraction itself or the runtime of the extracted code. Its
  **reproducible form is `tools/path_dependency_probe.py`** (*Verified facts*); what it cannot
  prove is covered by this repository's three layers and the committed probes.
