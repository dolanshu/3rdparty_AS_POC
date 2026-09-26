# Demo steps

Quick command checklist; what to say and why is in `docs/demo-script.md`.

## Before you start (once)

```bash
# Clone both repositories side by side first: the platform library (../as_platform), then this one.
git clone <library-repo> as_platform        # the platform library (sibling checkout, ../as_platform)
git clone <repo> && cd 3rdparty_AS_POC      # this repository
uv sync
make lint && make test
```

Note: if the environment is already set up, skip this.

## Two independent parts

**Part 1** is a set of one-shot commands: nothing stays running, each command starts its
own AS and mock on ephemeral ports, does one thing and exits. **Part 2** is the operations
console, which needs long-running processes and a browser. The two parts do not depend on
each other — run either one without the other.

**Part 3 (Phase 3)** is the live-load dashboard: a long-running AS chain, the load
generator driving real SIP traffic, and the enhanced console showing live charts and
topology. It builds on Part 2 by adding the generator and the Dashboard view.

### Part 1 — One-shot command-line demos

Each command is self-contained: it starts its own AS and mock on ephemeral ports, does one
thing, and exits. Run them in any order.

Ports and Call-IDs vary on every run; the examples below are trimmed from a real run.

#### 1.1 `make probe` — the SIP stack is real

```bash
make probe        # uv run python tools/sippy_probe.py
```

Shows: one INVITE into the sippy stack and one response out, plus the runtime versions.

```text
python      : 3.10.12
sippy       : 2.4.2
stack port  : 127.0.0.1:45889  (client port 45435)
--- response received --------------------------------------------
SIP/2.0 404 Probe
Call-ID: probe-59667@example.invalid
--- verdict --------------------------------------------------------
first line: SIP/2.0 404 Probe
minimal SipTransactionManager + ED2.loop() stack: OK
```

Expect: the verdict line `minimal SipTransactionManager + ED2.loop() stack: OK`.

#### 1.2 `make rules` — the policy is data

```bash
make rules        # uv run python tools/show_rules.py
```

Shows: the next hops, the rule table in evaluation order (18 declared, 17 enabled —
`R-DEFAULT-99` ships disabled), and the decisions for the sample numbers.

```text
next hops
   1  s-sbc-primary          udp://127.0.0.1:5061             Operator Service-SBC, primary trunk (mock in this POC)
   2  s-sbc-failover         udp://127.0.0.1:5061             Operator Service-SBC, second trunk used on failover
   ...
rules (evaluation order)
   10  R-EMG-01         110, 119, 120, 122                           route -> s-sbc-primary|s-sbc-failover
   ...
  400  R-BLOCK-90       +86168, +86169, 168, 169                     reject 603

decisions
  +8613800138000     route    R-MOB-CM-40      +8613800138000 -> 013800138000   s-sbc-primary -> s-sbc-failover
  6123               route    R-PBX-30         6123 -> +86216186123   office-pbx-primary -> office-pbx-secondary
  +861681234567      reject   R-BLOCK-90       603 AS-ROUTE-002  premium rate numbers are blocked by office policy
```

Expect: the rules are read from `config/routing_rules.yaml`, not from code.

#### 1.3 `make demo` — a successful call

```bash
make demo         # places a real call and narrates it; writes nothing
```

Shows: the 5-step transcript, with the routing decision and the final outcome.

```text
[2/5] routing decision
rule        : R-MOB-CM-40
disposition : route
translation : called number -> 013800138000
next hops   : s-sbc-primary -> s-sbc-failover
served by   : s-sbc-primary
...
[5/5] outcome
status      : 200
released    : True
cancelled   : False

demo result: call answered and released; number translation applied on the wire
```

Expect: the translation `+8613800138000 -> 013800138000` goes out on the wire and the
outcome is `status: 200` / `released: True`.

`make capture` is the optional variant of the same call: it stores the 14 messages under
`docs/specs/message-samples/` as samples (the capture is never committed).

#### 1.4 Failure branches

Each branch is a separate call and exits non-zero on purpose: the tool reports whether the
call was answered, and the rejection is the point being demonstrated.

```bash
uv run python tools/demo_call.py --called +9991234567
```

Shows: no rule matches, so the AS answers `404` and nothing goes to the next hop.

```text
[2/5] routing decision
rule        : None
disposition : None
...
      03 trunk -> 404    SIP/2.0 404 Not Found
...
status      : 404

demo result: call rejected with SIP 404 - the configured policy decision for this number
```

Expect: `SIP/2.0 404 Not Found`, exit status 1; no rule matched, so the decision is
`no_match` / `AS-ROUTE-001` (the transcript prints `rule: None` because there is no rule to
name).

```bash
uv run python tools/demo_call.py --called +861681234567
```

Shows: the premium-rate blocklist matches and the AS declines.

```text
[2/5] routing decision
rule        : R-BLOCK-90
disposition : reject
...
      03 trunk -> 603    SIP/2.0 603 Decline
...
status      : 603

demo result: call rejected with SIP 603 - the configured policy decision for this number
```

Expect: `SIP/2.0 603 Decline`, rule `R-BLOCK-90`, disposition `reject` (`AS-ROUTE-002`),
exit status 1.

```bash
uv run pytest tests/e2e -m e2e -k cancel
```

Shows: the caller abandons the call and the AS tears the outbound leg down.

```text
.                                                                        [100%]
1 passed, 4 deselected in 0.46s
```

Expect: `1 passed`.

Warning: do NOT use `+8613900000000` for the 404 branch — `+86139` is a China Mobile prefix
covered by `R-MOB-CM-40`, so that number is translated and routed normally.

#### 1.5 `make demo-fraud` — the anti-fraud AS (Phase 2, P8)

```bash
make demo-fraud        # two calls through the anti-fraud AS: one allowed, one rejected with 608
```

Shows: the screening verdict for a caller the data allows and for a caller on the block list,
and that the rejected call never reaches the S-SBC return side.

```text
anti-fraud AS POC - screening demo
topology   : S-SBC forward --UDP--> anti-fraud AS (608 or relay) --UDP--> S-SBC return (top Route)
ports      : anti-fraud-as 127.0.0.1:46592, trunk 47873, return 46573
screening  : config/caller_screening.yaml
verdict    : allow list -> block list -> call-rate window -> reputation

[1/2] call allowed and relayed
caller       : +86216180001
verdict      : allow
signal       : none
reason       : no screening signal rejected the call
sip.608 declared: True
final status : 200
released     : True

      expected SIP 200, observed 200; return INVITE delta 1

[2/2] call rejected with 608
caller       : +8613400000001
verdict      : reject
signal       : block_list
reason       : calling party is on the block list
list entry   : BL-0001
sip.608 declared: True
final status : 608
second leg   : none - the AS answered from the UAS side (RFC 8688, no Call-Info)

      expected SIP 608, observed 608; return INVITE delta 0

demo result: allow relayed to the S-SBC return side, reject answered 608 by the AS alone
```

Expect: `expected SIP 200, observed 200; return INVITE delta 1` for the allowed call and
`expected SIP 608, observed 608; return INVITE delta 0` for the rejected one; exit status 0.
The blocked caller is the first entry of `config/caller_screening.yaml`; swap it with
`--blocked-caller` to screen a different number.

#### 1.6 `make demo-chained` — two AS instances in series (Phase 2, P9/P9b)

The chain is **P9b / ADR-0014** (2026-09-23): AS instances **never** address each other.
The S-CSCF iFC orchestrator in `src/ims_mock/` triggers AS-1 and AS-2 in turn over the
S-SBC trunk; each AS returns its outbound INVITE to the top `Route` on the S-SBC **return**
side, and the terminating side is `S-CSCF → P-CSCF → terminating UAS`, never the S-SBC
return port. `*_SBC_PEER_*` is only the fallback for a trunk INVITE that carries no `Route`.

```bash
make demo-chained      # iFC chain: S-SBC -> AS-1 anti-fraud -> S-CSCF/iFC -> S-SBC -> AS-2 translation -> P-CSCF -> terminating UAS
```

Shows: the chain triggered by iFC, an allowed call traversing both B2BUAs and translated at
AS-2, the four AS-leg `Call-ID`s, the preserved ICID, and a `608` reject short-circuiting
before AS-2 and the terminating UAS.

Real transcript (captured 2026-09-24):

```text
chained AS POC - iFC-orchestrated chain (ADR-0014)
topology   : S-SBC -> AS-1 anti-fraud -> S-CSCF/iFC -> S-SBC -> AS-2 translation -> P-CSCF -> terminating UAS
ports      : AS-1 48627, AS-2 44788, return 47581, forward 47620, terminating 47678
wiring     : chain order in ims_mock orchestrator; peer knobs -> S-SBC return only

[1/2] allowed call relayed through both AS instances
caller            : +86216180001
AS-1 verdict      : allow
AS-2 rule         : R-MOB-CM-40
terminating called: 013800138000
final status      : 200

  four AS-leg Call-IDs (ADR-0014):
AS-1 trunk        : 65e1e6030953c32eaf9d8ecd846400f4
AS-1 outbound     : 65e1e6030953c32eaf9d8ecd846400f4-b2b_1
AS-2 trunk        : 792433dd594523356d726b29d5996a83
AS-2 outbound     : 792433dd594523356d726b29d5996a83-b2b_1
distinct Call-IDs : 4
Call-ID per leg   : True
ICID preserved    : True

[2/2] rejected call short-circuits at AS-1
AS-1 verdict      : reject
final status      : 608
AS-2 calls seen   : 0
terminating INVITEs: 0

--- verdict --------------------------------------------------------
allowed call completed through two B2BUAs    : OK
Call-ID regenerated on every leg             : OK
four distinct AS-leg Call-IDs                : OK
ICID preserved across every leg              : OK
608 reject short-circuited before AS-2       : OK
```

Expect: exit status 0 and the five `OK` verdict lines. Note the four `Call-ID` values are
**not** one value with suffixes applied twice: `AS-2 trunk` is a **new** value, because iFC
#2 is a new trunk INVITE. Ports and Call-IDs are ephemeral and vary per run.

### Part 2 — The console (long-running; independent of Part 1)

The console reads a long-running AS over its internal API. The one-shot calls in Part 1
start and stop their own AS, so they never show up in the console; this part keeps its own
processes running instead. Use three terminals:

```bash
make dev       # terminal 1: long-running AS on 127.0.0.1:5060, internal API on 127.0.0.1:8080
make mock      # terminal 2: long-running mock; places one office-to-mobile call on startup
make console   # terminal 3: console on 127.0.0.1:8081
```

Then open `http://127.0.0.1:8081`. The call that `make mock` placed on startup is the one
to watch in the live flow.

The call is choosable, not fixed: with no arguments `make mock` places the default
`office-to-mobile` call (`+86216180001` -> `+8613800138000`), and `--call CALLER=CALLED` picks
another (repeatable — one call per flag, placed in order on startup; `--repeat` loops them).
The mock dials the AS on `127.0.0.1:5060`, so `make dev` must already be running. `make mock`
forwards its arguments, so pass them with `ARGS`:

```bash
make mock                                            # default office-to-mobile call
make mock ARGS="--call +86216180001=+9991234567"      # no match -> 404
make mock ARGS="--call +86216180001=+861681234567"    # premium-rate block -> 603
make mock ARGS="--call +86216180001=+8613800138000 --call +86216180001=+9991234567 --repeat"
```

What the UI shows: a status bar (peer state, version, uptime, call counters), the live
message flow with direction colours, a Call-ID filter, a payload viewer, the matched rule
highlighted, a statistics dashboard and an SVG topology view — all inline, with no
third-party front-end libraries, so it works offline.

### Part 3 — Phase 3: Live-load dashboard (long-running, browser)

The enhanced console (P13) plus the load generator (P12) demonstrate real concurrent SIP
traffic visualised as live charts and a dynamic topology diagram.

Two flavours: **simple** (translation AS only, 3 terminals) and **full** (chained topology
with both AS instances, 5 terminals). Start with the simple one; add the chain if you want
to show the full Phase 2 + Phase 3 picture.

#### 3.0 Common prep: start the mock S-SBC return side (UAS)

The translation AS needs a next hop that answers 200 OK: the hop the rule catalogue names
(`127.0.0.1:5061` in `config/routing_rules.yaml`), which is the **S-SBC return** side the AS
sends its outbound INVITE to. Start the mock's UAS side there:

```bash
# Terminal A — mock S-SBC return side (UAS, answers 200 OK) — `make mock-return` does this
uv run python -m s_sbc_mock.main --listen-port 5061
```

It listens on `127.0.0.1:5061` and answers every INVITE with 180 → 200 → BYE.

#### 3.1 Simple variant — single translation AS (3 terminals)

Quickest way to show the dashboard.

```bash
# Terminal 1 — translation AS, SIP on 5060, internal API on 8080, next hop = S-SBC return
SBC_PEER_ADDRESS=127.0.0.1 SBC_PEER_PORT=5061 \
SIP_LISTEN_PORT=5060 INTERNAL_API_PORT=8080 \
  uv run python -m as_app.main
```

```bash
# Terminal 2 — load generator, points at translation AS on 5060
uv run python tools/call_load_generator.py \
  --as-port 5060 \
  --http-port 8765 \
  --target-concurrency 10 \
  --call-rate 3.0
```

```bash
# Terminal 3 — enhanced console on 8081
uv run python -m console.main \
  --port 8081 \
  --as-api-url http://127.0.0.1:8080 \
  --load-api-url http://127.0.0.1:8765
```

Open **http://127.0.0.1:8081**.

Then skip to [3.3 Demo flow](#33-demo-flow).

#### 3.2 Full variant — chained topology (5 terminals)

Shows the full picture: the iFC-orchestrated chain
`S-SBC → AS-1 anti-fraud → S-CSCF/iFC → S-SBC → AS-2 translation → P-CSCF → terminating UAS`
plus the live load. **The two AS processes never address each other** — the chain order lives
in the `src/ims_mock/` orchestrator, not in a peer knob; for the scripted version use
`scripts/phase3-demo.sh full`.

```bash
# Terminal 1 — anti-fraud AS (AS-1), SIP on 5062, internal API on 8082
# FRAUD_SBC_PEER_* = fallback peer only (S-SBC return) when the trunk INVITE has no Route.
# It must NOT point at the other AS — that wiring is obsolete (ADR-0014).
FRAUD_SIP_LISTEN_PORT=5062 FRAUD_INTERNAL_API_PORT=8082 \
FRAUD_SBC_PEER_ADDRESS=127.0.0.1 FRAUD_SBC_PEER_PORT=15062 \
FRAUD_ALLOWED_PEERS=127.0.0.1 \
  uv run python -m anti_fraud_as.main
```

```bash
# Terminal 2 — translation AS (AS-2), SIP on 5060, internal API on 8080
# Same: fallback peer only; the routed hop comes from the rule catalogue (127.0.0.1:5061)
SBC_PEER_ADDRESS=127.0.0.1 SBC_PEER_PORT=5061 \
SIP_LISTEN_PORT=5060 INTERNAL_API_PORT=8080 \
  uv run python -m as_app.main
```

```bash
# Terminal 3 — load generator, points at anti-fraud AS (AS-1 on 5062)
uv run python tools/call_load_generator.py \
  --as-port 5062 \
  --http-port 8765 \
  --target-concurrency 10 \
  --call-rate 3.0
```

```bash
# Terminal 4 — enhanced console on 8081, connects to AS-2's API + load generator API
uv run python -m console.main \
  --port 8081 \
  --as-api-url http://127.0.0.1:8080 \
  --load-api-url http://127.0.0.1:8765
```

Verify everything is healthy before the demo:

```bash
curl -s http://127.0.0.1:8082/healthz | python -m json.tool    # anti-fraud AS
curl -s http://127.0.0.1:8080/healthz | python -m json.tool    # translation AS
curl -s http://127.0.0.1:8765/healthz | python -m json.tool    # load generator
curl -s http://127.0.0.1:8081/healthz | python -m json.tool    # console
```

All four should return `{"status": "ok", ...}`.

Open **http://127.0.0.1:8081** in a browser. The Dashboard is the default view.

#### 3.3 Demo flow

**Step 1 — idle state**

Show the Dashboard:
- Status bar: both WS indicators (event ws, load ws) should show **live** (green).
- Line chart: flat line at 0 (no calls yet).
- Pie chart: all zero.
- Gauge: 0 / 10.
- Topology: the current mode's path. `simple` shows `S-SBC → Translation → S-SBC ret` with
  the Anti-fraud node dimmed; `fraud` shows `S-SBC → Anti-fraud → S-SBC ret` with Translation
  dimmed;
  `chained` switches to the iFC layout
  `Gen → S-SBC → Anti-fraud → iFC → Translation → UAS`. Thin grey lines mean no traffic yet.
- Trace panel: "no calls yet".

**Step 2 — start the load**

In the left-nav Load Generator panel, click **Start**.
Or from the command line:

```bash
curl -X POST http://127.0.0.1:8765/load/start
```

Watch the Dashboard come alive:
- **Line chart**: ramps up to ~10 active calls (rolling 30-second window).
- **Pie chart**: fills with active calls; completed calls accumulate over time.
- **Gauge**: needle moves toward 10 / 10 (target concurrency).
- **Topology**: links thicken proportionally to active calls; colour shifts to green.
- **Trace panel**: fills with live calls — filter by Call-ID with the text box.
- **Status bar**: `active` counter rises, `calls` total increments.

**Step 3 — adjust concurrency**

Drag the **Target** slider to 20 (or 50 for a denser demo), then release.
Or command line:

```bash
curl -X PUT http://127.0.0.1:8765/load/config \
  -H 'Content-Type: application/json' \
  -d '{"target_concurrency": 20}'
```

Watch:
- Gauge needle moves (target jumps to 20, active ramps up to match).
- Topology links get thicker as more calls flow.
- Line chart rises to the new plateau.

Then slide it back down to 5 to show the drain side.

**Step 4 — switch call types (full variant only)**

In the Call Types toggles, turn off some normal types and turn on F1–F4 (fraud types).
Then watch:
- Anti-fraud AS starts rejecting some calls with 608.
- Pie chart gains a red "rejected_608" slice.
- Topology l1 (S-CSCF → Anti-fraud) may show orange/red tint.
- Trace panel shows `call_rejected_608` events.

**Step 5 — legacy views (optional)**

Click through the left-nav to show the legacy views are still there:
- **Call Trace** — detailed per-call message flow.
- **Rules** — routing rules table.
- **Screening** — block/allow lists.
- **Statistics** — disposition counters.
- **About** — version info + vendored Chart.js attribution.

**Step 6 — stop the load**

Click **Stop** in the Load Generator panel.
Watch active calls drain to zero over ~5–10 seconds as in-flight calls complete.

#### 3.4 What this demonstrates

- **P12**: genuine concurrent SIP load from an external tool, no AS code modification.
- **P13**: live data visualisation with vendored Chart.js (no CDN, works offline).
- **Chained topology** (full variant): the call traverses two independent B2BUA
  processes, each with its own sippy event loop.
- **Event-driven UI**: the charts and topology update from WebSocket events, not polling.

## Notes

- `make demo` is repeatable and writes nothing.
- Capture evidence with `./tools/capture.sh`; never commit the capture.
- If a command fails, fix the script and the code rather than improvising.
- The Phase 3 dashboard demo works fully offline once the page is loaded — all assets
  (including Chart.js) are served from the console process itself.
