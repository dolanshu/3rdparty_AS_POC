# ADR-0003: UDP only, no TCP and no TLS on the trunk

- **Status:** Accepted for the POC trunk · **Superseded for the library's transport seam by
  ADR-0010** — the platform library ships a pluggable `Transport` with `TlsTransport` behind
  it (P11). This POC's own trunk is still UDP only; no TLS or TCP is deployed here.
- **Date:** 2026-09-15
- **Deciders:** project maintainer
- **Related:** `AGENT.md` section 2 and 9, `docs/production-gaps.md`, `docs/specs/index.md`

## Context

SIP runs over UDP, TCP and TLS (RFC 3261 section 18). A trunk between an operator and a
third party would in practice be TCP or TLS, both for message size limits and for
confidentiality and peer authentication.

The POC runs entirely on one machine against a local mock, and its purpose is to prove
the **call control and translation behaviour**, not transport hardening. Adding TCP and
TLS would add certificate handling, connection state and a second transport code path to
every piece of the stack.

## Decision

The AS and the mock speak **SIP over UDP only**. The `transport` parameter of a next hop
is fixed to `udp`. Neither TCP nor TLS is implemented, and neither SIP Digest nor
certificate-based peer authentication exists: the only peer check is the source address
allowlist `ALLOWED_PEERS`, which rejects anything else with `403` and `AS-PEER-001`.

## Consequences

- **The trunk is treated as untrusted but unauthenticated.** Every message from an
  address outside `ALLOWED_PEERS` is rejected at the earliest point.
- **No confidentiality or integrity on the wire.** Acceptable for a loopback demo; it is
  the single largest production gap.
- **Message size is limited** by the UDP datagram and by path MTU; a real trunk would
  need TCP or TLS for large INVITEs (many headers, large SDP).
- **No retransmission strategy beyond sippy's default timers.**
- Documentation, logs and demos must never imply that TLS or Digest exists.

## Gaps accepted

- TLS is mandatory in production on a public-internet trunk.
- Peer authentication must become an IP allowlist + SIP Digest + certificate check.
- Both rows are in `docs/production-gaps.md` and are restated in `SECURITY.md`.
