# ADR-0006: Signalling only — no RTP, no media anchoring

- **Status:** Accepted
- **Date:** 2026-09-15
- **Deciders:** project maintainer
- **Related:** `AGENT.md` section 1 and 2, `docs/specs/index.md`

## Context

The service performs number translation and routing. That decision is taken from the
signalling alone: the Request-URI and the number format. Media would only be needed if the
AS anchored it (transcoding, DTMF, announcements, recording), which it does not.

Handling media would mean an RTP stack, SDP negotiation and offer/answer validation, port
allocation for media, and a media relay — a second, substantially larger subsystem.

## Decision

The AS is **signalling only**:

- SDP bodies are **passed through verbatim**; the AS does not parse, validate or rewrite
  them (RFC 4566 is a pass-through reference only).
- No RTP is created, relayed or terminated (RFC 3550 is background reading).
- No MRF interaction, no announcements, no DTMF, no transcoding.
- Only the Request-URI and the number format are rewritten; all other headers are copied
  verbatim.

## Consequences

- **The offer/answer model is not enforced.** An INVITE without SDP, or with an SDP the
  far end cannot use, is passed through and fails at the endpoints, not in the AS.
- **No media-plane security** (no SRTP, no key management) is needed or provided.
- **The sippy dependency still pulls in media libraries** (`rtpsynth`, `g722`) even though
  no media code path is used; recorded in `docs/production-gaps.md` and in `NOTICE`.
- **The demo is a signalling demo.** Reviewers see message flow and translations; there is
  no audio, and the demo script says so.

## Gaps accepted

- SDP negotiation validation and optional media anchoring are production features.
- No CDR or media-quality records.
- Both rows are in `docs/production-gaps.md`.
