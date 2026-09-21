# Demo script

Duration: 5–10 minutes (10–14 with the anti-fraud section, §5a, and the chained section, §5b).
Audience: architecture reviewers and operator-side reviewers. Rehearse it before showing it;
if the script and `make demo` disagree, both are wrong (`AGENT.md` section 10).

**Status:** the whole script runs. Sections 1–7 are the Phase 1 path (M0–M4): the stack probe,
the rule data, a real translated call, the failure branches and the operations console — every
one of them rehearsed for M4. Sections 5a and 5b are the Phase 2 additions: §5a is
`make demo-fraud`, the anti-fraud AS, rehearsed for P8; §5b is `make demo-chained`, the two AS
instances in series, rehearsed for P9. The runs that recorded the evidence are in
`docs/acceptance/report.md`.

## 0. Setup (before the audience arrives)

```bash
# Clone both repositories side by side: the platform library first, then this repository.
git clone <library-repo> as_platform        # the platform library (sibling checkout, ../as_platform)
git clone <repo> && cd 3rdparty_AS_POC      # this repository
pip install uv
uv sync
make lint && make test
```

## 1. What this is (60 seconds)

> "This is a third-party Application Server: a B2BUA that sits outside the operator's IMS
> network and is reached over a SIP trunk from the operator's Service-SBC. The S-SBC, the
> S-CSCF and the core are mocked locally, and every peer address is configuration — the
> same code can be pointed at a real S-SBC by changing configuration only. It is a B2BUA
> and only a B2BUA: it terminates the incoming INVITE, translates the number, and
> originates a new INVITE back. Signalling only — no media."

Point at the diagram in `README.md` and at `docs/architecture/hld.md` section 1.

## 2. The stack is real (60 seconds)

```bash
make probe        # uv run python tools/sippy_probe.py
```

> "sippy 2.4.2 on Python 3.10: a minimal transaction manager plus its event loop bound on
> loopback, one INVITE in, one response out. This is the same stack the AS runs on."

The reviewer should see the INVITE, the sippy message log, and the verdict line
`minimal SipTransactionManager + ED2.loop() stack: OK`.

## 3. The routing policy is data (2 minutes)

```bash
make rules        # uv run python tools/show_rules.py
```

> "The dial plan is a YAML file, not code: 17 rules, six next hops. Emergency numbers
> first, then service short codes, office extensions, mobile ranges per operator, fixed
> lines, international, a premium-rate blocklist. Watch the decisions at the bottom:
> `+8613800138000` becomes `013800138000` and goes to the operator trunk; `6123` becomes
> `+86216186123` and goes to the office PBX; the premium-rate number is rejected with 603."

Show `config/routing_rules.yaml` and the `decisions` table. Emphasise: rules are read-only
on the console, edited as data, reloaded without a restart, and a broken edit keeps the
previous rule set alive.

## 4. One call, end to end (3 minutes)

```bash
make demo               # places a real call and narrates it
make capture            # the same call, its messages stored as samples
```

What the reviewer should see, in the transcript `make demo` prints:

1. `INVITE` arriving on the trunk with the called number in E.164 (`+8613800138000`).
2. The routing decision: rule `R-MOB-CM-40`, disposition `route`, the translation
   (`+8613800138000` → `013800138000`) and the ordered next hops with the one that served
   the call.
3. The outbound `INVITE` towards the S-SBC with the translated Request-URI.
4. Every message on the wire (`100 → 180 → 200 OK → ACK → BYE` on both legs), correlated
   by one Call-ID, and the final outcome.

`make demo` writes nothing, so it can be run as often as needed; `make capture` is what
refreshes `docs/specs/message-samples/`.

## 5. The failure branches (2 minutes)

Each branch is a call of its own — `make demo` takes the called number as an argument:

| What you do | What the reviewer sees |
| --- | --- |
| `uv run python tools/demo_call.py --called +9991234567` | `SIP/2.0 404 Not Found`, exit status 1; no rule matched, so the decision is `no_match` / `AS-ROUTE-001` (the transcript prints `rule: None` because there is no rule to name) |
| `uv run python tools/demo_call.py --called +861681234567` | `SIP/2.0 603 Decline`, rule `R-BLOCK-90`, disposition `reject` (`AS-ROUTE-002`), exit status 1 |
| `uv run pytest tests/e2e -m e2e -k cancel` | `1 passed`; the caller abandons and the AS tears the outbound leg down (disposition `abandoned`) |

`+9991234567` is the no-match example: `+999` is not in any rule. Do **not** use
`+8613900000000` for this branch — `+86139` is a China Mobile prefix covered by
`R-MOB-CM-40`, so that number is translated and routed (`200 OK`, exit status 0).

A rejected call exits non-zero on purpose: the tool reports whether the call was answered.
The rejection itself is the point being demonstrated.

## 5a. The second AS — anti-fraud screening (2 minutes)

```bash
make demo-fraud        # two calls through the anti-fraud AS: one allowed, one rejected
```

> "Phase 2 adds a second, independently runnable AS process at the same trunk boundary. This
> one does not translate anything: it inspects the **calling** party and returns a verdict.
> A caller the screening data allows is relayed towards the core unchanged; a caller on the
> block list is answered `608 Rejected` (RFC 8688) by the AS itself — no second leg, no media
> announcement, and no `Call-Info`. The `608` is what a generic `403` or `603` cannot say: an
> automated anti-fraud engine made the decision."

What the reviewer should see, in the transcript `make demo-fraud` prints:

1. The topology line `emulated S-CSCF --UDP--> anti-fraud AS (608 Rejected) --UDP--> emulated
   core network` and the screening file in use (`config/caller_screening.yaml`).
2. The fixed verdict order: `allow list -> block list -> call-rate window -> reputation`.
3. Call 1 (`+86216180001`): `verdict: allow`, `signal: none`, `final status: 200`,
   `core INVITE delta 1` — the allowed call really reached the emulated core.
4. Call 2 (`+8613400000001`): `verdict: reject`, `signal: block_list`,
   `list entry: BL-0001`, `final status: 608`, `second leg: none ... (RFC 8688, no
   Call-Info)`, `core INVITE delta 0` — the rejected call never reached the core, because the
   reject path is UAS behaviour and originates no second leg.

Point out that each demo allocates its own ephemeral ports, so this section and `make demo`
do not interfere with each other, and that the number-translation path is unchanged: a second
AS is a second use case, not a change to the first one. `make demo-fraud` writes nothing, so it
is as repeatable as `make demo`.

## 5b. The chain — two AS instances in series (2 minutes)

```bash
make demo-chained      # SBC -> AS-1 anti-fraud -> AS-2 number translation -> core, wired by config
```

> "The two AS instances chain by configuration alone: AS-1's next hop is pointed at AS-2's
> listen address and AS-2's rule set selects the core. No iFC emulation in the mock, no code
> shared between the two AS instances, and no new port or environment variable — it is the same
> `next_hops` catalogue that changed. Two B2BUAs in series mean a call carries **three**
> `Call-ID`s, one per leg, so each instance writes its own trace and there is no cross-AS
> correlation by `Call-ID`; the end-to-end `P-Charging-Vector` ICID survives the whole chain
> but nothing is keyed on it. The demo is a guard: it asserts all of that — including the
> reject's silence as an absence — and exits non-zero if it does not hold."

What the reviewer should see, in the transcript `make demo-chained` prints:

1. The topology line `emulated S-CSCF --UDP--> AS-1 anti-fraud --UDP--> AS-2 number
   translation --UDP--> emulated core` and the wiring line `AS-1 next hop = AS-2 listen
   address; AS-2 next hop = the rule set`.
2. Call 1 (`+86216180001` → `+8613800138000`): `AS-1 verdict: allow`, `AS-1 signal: none`,
   AS-2's matched rule `R-MOB-CM-40`, `core called number: 013800138000`, `final status: 200`,
   `released: True` — the allowed call really traversed both B2BUAs and was translated at AS-2.
3. The three per-leg `Call-ID`s and their derivation: `S-CSCF Call-ID` `dc6cbf77…e621`,
   `AS-2 trunk Call-ID` `dc6cbf77…e621-b2b_1`, `core Call-ID` `dc6cbf77…e621-b2b_1-b2b_1`,
   with `distinct Call-IDs: 3` and `Call-ID per leg: True (each transition is
   outbound_call_id of the previous one)`.
4. The preserved ICID: `S-CSCF ICID`, `AS-2 ICID` and `core ICID` all read
   `poc-chained-allow`, with `ICID preserved: True`.
5. Call 2 (`+8613400000001`): `AS-1 verdict: reject`, `final status: 608 (608 Rejected, no
   second leg)`, `AS-2 calls seen: 0` and `core INVITEs seen: 0` — the reject short-circuits
   before AS-2 and the core, and the absence is the assertion.
6. The five `OK` verdict lines: `allowed call completed through two B2BUAs`, `608 reject
   short-circuited before AS-2`, `Call-ID regenerated on every leg`, `three distinct Call-IDs
   across the chain` and `ICID preserved across every leg`.

Ports and Call-IDs are ephemeral and vary per run. `make demo-chained` writes nothing, so it is
as repeatable as `make demo`.

## 6. The console (1 minute)

The console is a separate process (ADR-0002). It needs a long-running AS to read from, so
for this section run the AS and the mock in two terminals, then the console in a third:

```bash
make dev       # terminal 1: AS on 127.0.0.1:5060, internal API on 127.0.0.1:8080
make mock      # terminal 2: mock S-SBC places one office-to-mobile call on startup
make console   # terminal 3: console on 127.0.0.1:8081, reading the AS API at :8080
```

Open `http://127.0.0.1:8081`. The call placed by `make mock` is visible in the live flow.
Status bar with peer state and version, live message flow with direction colours, Call-ID
filter, payload viewer, the matched rule highlighted, the statistics dashboard and the SVG
topology. No third-party front-end libraries, so it works offline.

`make demo` (section 4) runs its own AS and mock on ephemeral ports, so those calls do not
appear in a console pointed at the long-running AS — use `make dev` + `make mock` here.

## 7. Closing line

> "Everything that is deliberately missing — TLS, Digest, media, real HA, charging — is
> registered in `docs/production-gaps.md` with what production would require. Nothing is
> silently skipped."

## Notes

- `make demo` places a real call; `make rules` prints the rule table it used to print.
- Capture evidence during the demo with `./tools/capture.sh`; never commit the capture.
- If anything in this script fails, do not improvise: fix the script and the code.
