# SIP message samples

Real trunk-side messages captured from actual runs of the POC with
`tools/capture_call.py` (the `make capture` target); `make demo` writes nothing, so it does
not produce samples. They are referenced by the interface specification and by acceptance
evidence.

**The sample files are generated, not committed.** `docs/specs/message-samples/*.txt` is
gitignored, so a capture never dirties the working tree. This `README.md` is the tracked
part of the folder: it records the naming convention and the scenario, and the samples
themselves are reproduced with `make capture` (or `uv run python tools/capture_call.py`).

## Naming

```text
<sequence>-<direction>-<method-or-status>[-<qualifier>].txt
```

- `sequence` — two digits, order within the scenario
- `direction` — `in` (S-SBC -> AS) or `out` (AS -> S-SBC)
- `method-or-status` — `invite`, `180`, `200`, `ack`, `bye`, `cancel`

Example: `03-out-invite-core.txt` is the INVITE the AS originates on the core leg after
number translation.

## Rules

1. Samples are captured, never hand-written. Regenerate them when wire behaviour changes.
2. One file, one message, verbatim bytes (CRLF line endings preserved where relevant).
3. No real subscriber data: use documentation number ranges only.
4. Each scenario gets a short `README` or a section naming the scenario and the rule set
   used, so a reviewer can reproduce it.
5. A capture clears the previously generated samples first (everything in this directory
   except this `README.md`), so the folder always holds exactly the messages of the most
   recent call — no orphaned files from an earlier, longer capture.

## Scenario: M2 translated call (`office-to-mobile`)

Captured on **2026-09-19** with

```text
uv run python tools/capture_call.py
```

which runs the AS and the mock S-SBC on loopback UDP with dynamically allocated ports,
places one call and writes every message of it to this directory. The AS now applies
number translation (M2): the called number `+8613800138000` (China Mobile, E.164) is
rewritten to `013800138000` (national format) by rule `R-MOB-CM-40` before the outbound
INVITE is originated.

| Item | Value |
| --- | --- |
| Scenario | `office-to-mobile` (`src/s_sbc_mock/uac.py`) |
| Calling party | `+86216180001` (documentation range) |
| Called party (in) | `+8613800138000` (documentation range, E.164) |
| Called party (out) | `013800138000` (national format, translated) |
| Rule set | `config/routing_rules.yaml`, `sample-office-routing` (17 rules, 6 next hops) |
| Matched rule | `R-MOB-CM-40` (China Mobile, E.164 in, national out) |
| Ports | allocated per capture (dynamic, never 5060) |
| Call-ID (trunk) | generated per capture by the mock's SIP stack |
| Call-ID (core) | the trunk Call-ID plus the AS suffix `-b2b_1` |

Ports differ on every capture because they are allocated dynamically, and the trunk
Call-ID differs too, because the mock's stack generates it. The two legs do **not** share
a Call-ID: the AS gives the outbound leg its own, derived from the trunk one by appending
its B2BUA suffix `-b2b_1` (the style sippy's own `CCB2BUA` uses), so the core-leg Call-ID
is `<trunk Call-ID>-b2b_1` — for example `03-out-invite-core.txt` carries the Call-ID of
`01-in-invite-trunk.txt` with that suffix, and the `From` tag and `CSeq` differ as well
because they are regenerated for the outbound dialog. What must not differ across the two
legs is the pass-through header set and the SDP body: the headers of
`01-in-invite-trunk.txt` reappear unchanged in `03-out-invite-core.txt`. What **does**
change in M2 is the called number in the Request-URI, `To` and `Contact`:
`+8613800138000` on the trunk becomes `013800138000` on the core leg.

| File | Message |
| --- | --- |
| `01-in-invite-trunk.txt` | INVITE from the emulated S-CSCF, Request-URI `sip:+8613800138000@...` |
| `02-out-100-trunk.txt` | 100 Trying towards the emulated S-CSCF |
| `03-out-invite-core.txt` | INVITE the AS originates, Request-URI `sip:013800138000@...` (translated) |
| `04-in-100-core.txt` | 100 Trying from the emulated core network |
| `05-in-180-core.txt` | 180 Ringing from the emulated core network |
| `06-out-180-trunk.txt` | 180 Ringing towards the emulated S-CSCF |
| `07-in-200-core.txt` | 200 OK from the emulated core network, SDP echoed back |
| `08-out-ack-core.txt` | ACK towards the emulated core network |
| `09-out-200-trunk.txt` | 200 OK towards the emulated S-CSCF |
| `10-in-ack-trunk.txt` | ACK from the emulated S-CSCF |
| `11-in-bye-core.txt` | BYE from the emulated core network (talk time over) |
| `12-out-200-core.txt` | 200 OK for that BYE |
| `13-out-bye-trunk.txt` | BYE the AS relays towards the emulated S-CSCF |
| `14-in-200-trunk.txt` | 200 OK for that BYE |
