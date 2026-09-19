# Tools

Scripts used to develop, probe and demonstrate the AS. They are development tools, not
runtime components: nothing in `src/` depends on them.

| Tool | Purpose |
| --- | --- |
| `tools/sippy_probe.py` | Starts a minimal sippy stack (`SipTransactionManager` + `ED2.loop()`) and reports what it really does. This is how sippy behaviour is verified instead of assumed (`AGENT.md` section 6). |
| `tools/anti_fraud_probe.py` | Proves that sippy emits an arbitrary 6xx through `CCEventFail((status, phrase, None))` over real UDP — specifically `608 Rejected` (RFC 8688), which the number-translation AS never emitted. It asserts the whole status line (code **and** reason phrase) and exits non-zero on a mismatch. This is the design evidence recorded in ADR-0007. |
| `tools/chained_as_probe.py` | Runs **two AS instances in series** — the anti-fraud AS relaying an allowed INVITE into the number-translation AS — on dynamically allocated ports and reports what the chain really does: an allowed call completes through both B2BUAs, a `608` reject short-circuits before AS-2, and the dialog `Call-ID` each hop sees. This is the design evidence recorded in ADR-0008. It is a design instrument, not a test: pytest does not collect it and it does not run in CI. |
| `tools/demo_fraud_call.py` | Runs the anti-fraud AS on its own ports and places two real calls through it — one the screening data allows (relayed to the core, `200 OK`) and one from the block list (answered `608 Rejected` by the AS, no second leg). This is what `make demo-fraud` runs; it writes nothing. |
| `tools/show_rules.py` | Prints the active rule set and the decision for sample numbers; this is what `make rules` runs. |
| `tools/demo_call.py` | Places one real call and narrates it — routing decision, translation, every message on the wire, outcome. This is what `make demo` runs; it writes nothing. |
| `tools/capture.sh` | Captures UDP traffic on the trunk ports into `captures/` for acceptance evidence (`AGENT.md` section 4.8). |
| `tools/capture_call.py` | Runs the AS and the mock S-SBC on loopback UDP with dynamic ports, places one call and writes every message of it to `docs/specs/message-samples/`. This is how message samples stay captured rather than hand-written. A capture clears the folder's previously generated samples (everything except its `README.md`) before writing, so the directory always holds exactly the most recent call. It also exports `run_call`, which `tools/demo_call.py` reuses so both can never disagree about what the stack does. |

## Running

```bash
uv run python tools/sippy_probe.py
uv run python tools/anti_fraud_probe.py          # the 608 reject path, over real UDP
uv run python tools/chained_as_probe.py          # two B2BUAs in series, over real UDP
uv run python tools/demo_call.py --called +8613800138000
uv run python tools/demo_fraud_call.py           # allow + 608 reject, narrated
uv run python tools/show_rules.py --evaluate +8613800138000
uv run python tools/capture_call.py
./tools/capture.sh --port 5060
```

## Rules for new tools

- A tool that claims something about sippy must print the real output; a claim without an
  executed run is not evidence (`AGENT.md` §14 rule 6, report honestly).
- Tools may import from `src/`, never the other way round.
- No tool may commit captures, payloads with real numbers or environment files.
