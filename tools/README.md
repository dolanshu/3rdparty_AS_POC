# Tools

Scripts used to develop, probe and demonstrate the AS. They are development tools, not
runtime components: nothing in `src/` depends on them.

| Tool | Purpose |
| --- | --- |
| `tools/sippy_probe.py` | Starts a minimal sippy stack (`SipTransactionManager` + `ED2.loop()`) and reports what it really does. This is how sippy behaviour is verified instead of assumed (`AGENT.md` section 6). |
| `tools/show_rules.py` | Prints the active rule set and the decision for sample numbers; this is what `make rules` runs. |
| `tools/demo_call.py` | Places one real call and narrates it — routing decision, translation, every message on the wire, outcome. This is what `make demo` runs; it writes nothing. |
| `tools/capture.sh` | Captures UDP traffic on the trunk ports into `captures/` for acceptance evidence (`AGENT.md` section 4.8). |
| `tools/capture_call.py` | Runs the AS and the mock S-SBC on loopback UDP with dynamic ports, places one call and writes every message of it to `docs/specs/message-samples/`. This is how message samples stay captured rather than hand-written. It also exports `run_call`, which `tools/demo_call.py` reuses so both can never disagree about what the stack does. |

## Running

```bash
uv run python tools/sippy_probe.py
uv run python tools/demo_call.py --called +8613800138000
uv run python tools/show_rules.py --evaluate +8613800138000
uv run python tools/capture_call.py
./tools/capture.sh --port 5060
```

## Rules for new tools

- A tool that claims something about sippy must print the real output; a claim without an
  executed run is not evidence (`AGENT.md` section 14.6).
- Tools may import from `src/`, never the other way round.
- No tool may commit captures, payloads with real numbers or environment files.
