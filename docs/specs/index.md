# Normative references

Everything about SIP behaviour in this repository must be traceable to one of the
references below. Where a reference and an assumption disagree, the reference wins; where
the reference is ambiguous, stop and ask.

| ID | Reference | Version / date | Use in this project |
| --- | --- | --- | --- |
| RFC 3261 | SIP: Session Initiation Protocol | IETF, June 2002 | **Primary.** Methods, request/response syntax, header fields, transactions, dialogs, URI forms |
| RFC 4566 | SDP: Session Description Protocol | IETF, July 2006 | Message body that we pass through unmodified |
| RFC 3550 | RTP: A Transport Protocol for Real-Time Applications | IETF, July 2003 | Background for the media we deliberately do not handle |
| 3GPP TS 24.229 | IP multimedia call control protocol based on SIP and SDP | Release as recorded below | Context for iFC triggering and the ISC interface on the S-CSCF side of the S-SBC |
| 3GPP TS 23.228 | IP Multimedia Subsystem (IMS) | Release as recorded below | Architecture context: where the S-SBC sits, why the AS is outside the core |

Retrieval date for all entries: **2026-09-15**. When a document is downloaded or a
specific release is chosen, record the exact release number and file name here.

## Rules

1. Method names, header names, status codes and URI syntax come from these documents or
   from observed sippy behaviour — never from memory.
2. Cite the document and section when a protocol decision is made (in code comments and
   in `docs/architecture/lld.md`).
3. `docs/specs/message-samples/` holds real messages, generated with `make capture` and
   gitignored (only the folder `README.md` is tracked); a sample that no longer matches
   real traffic is a bug and must be regenerated.
