# Demo steps

Quick command checklist; the narration is in `docs/demo-script.md`.

## 0. Setup

```bash
uv sync
make lint && make test
```

Expect: the environment installs from `uv.lock`; lint is clean and all three test layers pass.

## 1. The stack is real

```bash
make probe        # uv run python tools/sippy_probe.py
```

Expect: one INVITE in, one response out, and the verdict line
`minimal SipTransactionManager + ED2.loop() stack: OK`.

## 2. The routing policy is data

```bash
make rules        # uv run python tools/show_rules.py
```

Expect: the rule table (17 rules, six next hops) followed by the decisions at the bottom.

## 3. One call, end to end

```bash
make demo         # places a real call and narrates it; writes nothing
```

Expect: the 5-step transcript (`[1/5]` … `[5/5]`) ending with the outcome line
`demo result: call answered and released; number translation applied on the wire`.

```bash
make capture      # the same call, its messages stored as samples
```

Expect: `docs/specs/message-samples/` refreshed with 14 sample files (the capture is NOT
committed).

## 4. The failure branches

Each branch is a call of its own and exits non-zero on purpose.

```bash
uv run python tools/demo_call.py --called +9991234567
```

Expect: `SIP/2.0 404 Not Found`, decision `no_match` / `AS-ROUTE-001`.

```bash
uv run python tools/demo_call.py --called +861681234567
```

Expect: `SIP/2.0 603 Decline`, rule `R-BLOCK-90`, `AS-ROUTE-002`.

```bash
uv run pytest tests/e2e -m e2e -k cancel
```

Expect: `1 passed` (the caller abandons; the AS tears the outbound leg down).

Warning: do NOT use `+8613900000000` for the 404 branch — `+86139` is a China Mobile prefix
covered by `R-MOB-CM-40`, so that number is translated and routed normally.

## 5. The console

The console is a separate process and needs a long-running AS. Use three terminals:

```bash
make dev       # terminal 1: AS on 127.0.0.1:5060, internal API on 127.0.0.1:8080
make mock      # terminal 2: mock S-SBC, places one office-to-mobile call on startup
make console   # terminal 3: console on 127.0.0.1:8081
```

Then open `http://127.0.0.1:8081`.

Caveat: `make demo` runs its own AS and mock on ephemeral ports, so those calls do NOT
appear in a console pointed at the long-running AS — use `make dev` + `make mock` here.

## Notes

- `make demo` is repeatable; `make capture` is what refreshes `docs/specs/message-samples/`.
- Capture evidence during the demo with `./tools/capture.sh`; never commit the capture.
- If a command fails, fix the script and the code rather than improvising.
