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
