# SIP message samples

Real trunk-side messages captured from actual runs of the POC (`make demo` or the e2e
suite). They are referenced by the interface specification and by acceptance evidence.

## Naming

```text
<sequence>-<direction>-<method-or-status>[-<qualifier>].txt
```

- `sequence` — two digits, order within the scenario
- `direction` — `in` (S-SBC -> AS) or `out` (AS -> S-SBC)
- `method-or-status` — `invite`, `180`, `200`, `ack`, `bye`, `cancel`

Example: `02-out-invite-translated.txt` is the INVITE the AS originates after number
translation.

## Rules

1. Samples are captured, never hand-written. Regenerate them when wire behaviour changes.
2. One file, one message, verbatim bytes (CRLF line endings preserved where relevant).
3. No real subscriber data: use documentation number ranges only.
4. Each scenario gets a short `README` or a section naming the scenario and the rule set
   used, so a reviewer can reproduce it.

## Scenario: M1 complete call (`office-to-mobile`)

Captured on **2026-09-16** with

```text
uv run python tools/capture_call.py
```

which runs the AS and the mock S-SBC on loopback UDP with dynamically allocated ports,
places one call and writes every message of it to this directory.

| Item | Value |
| --- | --- |
| Scenario | `office-to-mobile` (`src/s_sbc_mock/uac.py`) |
| Calling party | `+86216180001` (documentation range) |
| Called party | `+8613800138000` (documentation range) |
| Rule set | `config/routing_rules.yaml`, `sample-office-routing` (17 rules, 6 next hops) |
| Ports of this capture | AS `127.0.0.1:47183`, mock core side `127.0.0.1:46621`, mock trunk side `127.0.0.1:46849` |
| Call-ID | `66214a32501ea3d6a9aaf48db78f1a6c` |

Ports differ on every capture because they are allocated dynamically; the Call-ID differs
too, because the stack generates it. What must not differ is the message content: the
pass-through headers and the SDP body of `01-in-invite-trunk.txt` reappear unchanged in
`03-out-invite-core.txt`, only the Request-URI, `Via`, `Contact` and `User-Agent` change.

| File | Message |
| --- | --- |
| `01-in-invite-trunk.txt` | INVITE from the emulated S-CSCF, received on the trunk |
| `02-out-100-trunk.txt` | 100 Trying towards the emulated S-CSCF |
| `03-out-invite-core.txt` | INVITE the AS originates towards the emulated core network |
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
