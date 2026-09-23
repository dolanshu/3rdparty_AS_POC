# ADR-0005: Mock the S-SBC with the same SIP stack as the AS

- **Status:** Accepted
- **Date:** 2026-09-15
- **Deciders:** project maintainer
- **Related:** ADR-0001, `AGENT.md` section 1 and 5

## Context

We implement the external AS only. The S-SBC, the S-CSCF and the core network are out of
scope, but the POC needs something to place INVITEs on the trunk and something to answer
the INVITE the AS originates back.

Options considered:

| Option | Assessment |
| --- | --- |
| A real SIPp/sipp-driven scenario or a third-party softswitch | Realistic traffic, but a second toolchain, a second configuration language and no shared behaviour guarantees |
| Hand-written UDP scripts that emit canned messages | Cheap, but every protocol detail (branch, tags, CSeq, retransmissions) would be our own invention — exactly what `AGENT.md` section 14 forbids |
| **A mock built on sippy, the same stack as the AS** | Both ends share identical protocol behaviour; the mock is ordinary Python we can test and debug; the stack is already a dependency |

## Decision

`src/s_sbc_mock/` is a mock **operator S-SBC** built on **sippy**, with two UDP endpoints.
Neither the S-CSCF nor the S-SBC is a B2BUA; the third-party AS is the only B2BUA (UAS on
the trunk, UAC on the outbound leg with a new `Call-ID`).

- **Forward side (`15060`)** — emulates the S-SBC forwarding the operator INVITE towards
  the AS trunk (`5060`), carrying a `Route` set that points back at the S-SBC return
  interface. Driven by `CallScenario` data (CANCEL, ACK, BYE on the trunk leg).
- **Return side (`15061`)** — emulates the S-SBC interface that receives the translated
  INVITE the AS originates (top `Route`, RFC 3261). Answers with `100 Trying`,
  `180 Ringing`, `200 OK`, then BYE for the POC.

Peer addresses and ports are configuration, so the mock can be swapped for a real S-SBC
without a code change. `src/as_app` never imports from the mock; only tests may.

## Consequences

- **Identical protocol behaviour on both ends**, which removes a whole class of "works
  against my script" bugs.
- **A shared failure mode**: a sippy bug or a wrong assumption affects both sides. This is
  why sippy behaviour is verified by running it (`tools/sippy_probe.py`), and why message
  samples in `docs/specs/message-samples/` come from real exchanges.
- **The mock is not a conformance test.** It proves the AS behaves correctly against
  *itself*; it says nothing about interoperability with a real S-SBC.

## Gaps accepted

- No iFC evaluation, no subscription data, no S-CSCF behaviour beyond a single triggered
  INVITE.
- No negative protocol testing (malformed messages, hostile retransmissions).
- Registered in `docs/production-gaps.md`.
