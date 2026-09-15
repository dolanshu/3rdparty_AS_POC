# Demo script

Duration: 5–10 minutes. Audience: architecture reviewers and operator-side reviewers.
Rehearse it before showing it; if the script and `make demo` disagree, both are wrong
(`AGENT.md` section 10).

**Status in M0:** the call demo is **not available yet**. Section 4 onwards is the M1/M3
script and is marked as such. What M0 demos is the rule data and the verified stack.

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
make demo         # uv run python tools/show_rules.py
```

> "The dial plan is a YAML file, not code: 17 rules, six next hops. Emergency numbers
> first, then service short codes, office extensions, mobile ranges per operator, fixed
> lines, international, a premium-rate blocklist. Watch the decisions at the bottom:
> `+8613800138000` becomes `013800138000` and goes to the operator trunk; `6123` becomes
> `+86216186123` and goes to the office PBX; the premium-rate number is rejected with 603."

Show `config/routing_rules.yaml` and the `decisions` table. Emphasise: rules are read-only
on the console, edited as data, reloaded without a restart, and a broken edit keeps the
previous rule set alive.

## 4. From M1: one call, end to end (3 minutes — not available in M0)

```bash
make docker-up          # as + s-sbc-mock + console
make demo               # places a call and prints the Call-ID keyed trace
```

What the reviewer should see:

1. `INVITE` arriving on the trunk with the called number in E.164.
2. The trace line with the rule that matched (`R-MOB-CM-40`) and the translation
   (`+8613800138000` → `013800138000`).
3. The outbound `INVITE` towards the S-SBC with the translated Request-URI and the
   original SDP passed through unchanged.
4. `100 → 180 → 200 OK → ACK → BYE` on both legs, correlated by one Call-ID.

## 5. From M2: the failure branches (2 minutes — not available in M0)

| What you do | What the reviewer sees |
| --- | --- |
| Dial an unroutable number | `404 Not Found`, log code `AS-ROUTE-001`, counter `no_match` |
| Dial a premium-rate number | `603 Decline`, log code `AS-ROUTE-002`, rule `R-BLOCK-90` |
| Abandon before answer | `CANCEL`, both legs torn down, disposition `abandoned` |

## 6. From M3: the console (1 minute — not available in M0)

Open `http://127.0.0.1:8081`. Status bar with peer state and version, live message flow
with direction colours, Call-ID filter, payload viewer, the matched rule highlighted, the
statistics dashboard and the SVG topology. No third-party front-end libraries, so it works
offline.

## 7. Closing line

> "Everything that is deliberately missing — TLS, Digest, media, real HA, charging — is
> registered in `docs/production-gaps.md` with what production would require. Nothing is
> silently skipped."

## Notes

- `make demo` in M0 only prints the rule set; the call demo replaces it in M1/M2.
- Capture evidence during the demo with `./tools/capture.sh`; never commit the capture.
- If anything in this script fails, do not improvise: fix the script and the code.
