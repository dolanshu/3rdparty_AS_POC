# Demo script

Duration: 5–10 minutes. Audience: architecture reviewers and operator-side reviewers.
Rehearse it before showing it; if the script and `make demo` disagree, both are wrong
(`AGENT.md` section 10).

**Status:** sections 1–5 run today (M0–M2 are complete): the stack probe, the rule data, a
real translated call and the failure branches. Section 6 needs the console, which is M3;
it is marked as not available yet.

## 0. Setup (before the audience arrives)

```bash
git clone <repo> && cd 3rtparty_AS_POC
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
| `uv run python tools/demo_call.py --called +8613900000000` | `404 Not Found`, log code `AS-ROUTE-001`, disposition `no_match` |
| `uv run python tools/demo_call.py --called +861681234567` | `603 Decline`, log code `AS-ROUTE-002`, rule `R-BLOCK-90` |
| `uv run pytest tests/e2e -m e2e -k cancel` | `CANCEL`, both legs torn down, disposition `abandoned` |

A rejected call exits non-zero on purpose: the tool reports whether the call was answered.
The rejection itself is the point being demonstrated.

## 6. The console (1 minute — M3, not available yet)

Open `http://127.0.0.1:8081`. Status bar with peer state and version, live message flow
with direction colours, Call-ID filter, payload viewer, the matched rule highlighted, the
statistics dashboard and the SVG topology. No third-party front-end libraries, so it works
offline.

## 7. Closing line

> "Everything that is deliberately missing — TLS, Digest, media, real HA, charging — is
> registered in `docs/production-gaps.md` with what production would require. Nothing is
> silently skipped."

## Notes

- `make demo` places a real call; `make rules` prints the rule table it used to print.
- Capture evidence during the demo with `./tools/capture.sh`; never commit the capture.
- If anything in this script fails, do not improvise: fix the script and the code.
