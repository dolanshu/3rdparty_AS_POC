# Demo steps

Quick command checklist; what to say and why is in `docs/demo-script.md`.

## Before you start (once)

```bash
uv sync
make lint && make test
```

Note: if the environment is already set up, skip this.

## Two independent parts

**Part 1** is a set of one-shot commands: nothing stays running, each command starts its
own AS and mock on ephemeral ports, does one thing and exits. **Part 2** is the operations
console, which needs long-running processes and a browser. The two parts do not depend on
each other — run either one without the other.

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

Shows: the next hops, the 17-rule table in evaluation order, and the decisions for the
sample numbers.

```text
next hops
   1  s-sbc-primary          udp://127.0.0.1:15061            Operator Service-SBC, primary trunk (mock in this POC)
   2  s-sbc-failover         udp://127.0.0.1:15062            Operator Service-SBC, second trunk used on failover
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
and that the rejected call never reaches the core.

```text
anti-fraud AS POC - screening demo
topology   : emulated S-CSCF --UDP--> anti-fraud AS (608 Rejected) --UDP--> emulated core network
ports      : anti-fraud-as 127.0.0.1:47280, trunk 47064, core 48564
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

      expected SIP 200, observed 200; core INVITE delta 1

[2/2] call rejected with 608
caller       : +8613400000001
verdict      : reject
signal       : block_list
reason       : calling party is on the block list
list entry   : BL-0001
sip.608 declared: True
final status : 608
second leg   : none - the AS answered from the UAS side (RFC 8688, no Call-Info)

      expected SIP 608, observed 608; core INVITE delta 0

demo result: allow relayed to the core, reject answered 608 by the AS alone
```

Expect: `expected SIP 200, observed 200; core INVITE delta 1` for the allowed call and
`expected SIP 608, observed 608; core INVITE delta 0` for the rejected one; exit status 0.
The blocked caller is the first entry of `config/caller_screening.yaml`; swap it with
`--blocked-caller` to screen a different number.

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

## Notes

- `make demo` is repeatable and writes nothing.
- Capture evidence with `./tools/capture.sh`; never commit the capture.
- If a command fails, fix the script and the code rather than improvising.
