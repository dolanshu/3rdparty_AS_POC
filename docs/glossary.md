# Glossary

Telecom terminology used in this repository. Where a term has a normative definition, the
reference is named; see `docs/specs/index.md`.

| Term | Meaning | Reference |
| --- | --- | --- |
| AS (Application Server) | A SIP entity that provides services. Here: the **third-party** AS, outside the operator's IMS network. | 3GPP TS 23.228 |
| B2BUA (Back-to-Back User Agent) | An entity that terminates a SIP session and originates a new one; both legs are separate dialogs. This AS is a B2BUA and never a redirect server. | RFC 3261 section 6 |
| Call-ID | SIP header that identifies a call; the correlation key for logs, traces and console events in this project. | RFC 3261 section 8.1.1.4 / 20.8 |
| Called number | The destination number, carried in the user part of the Request-URI; the object of number translation. | RFC 3261 section 19.1 |
| Calling number | The originating party; on an IMS trunk it is carried in `P-Asserted-Identity`. | 3GPP TS 24.229 |
| CDR (Call Detail Record) | Charging record per call leg. Not generated in this POC. | — |
| Dialog | Peer-to-peer SIP relationship maintained between two UAs; a B2BUA has one per leg. | RFC 3261 section 12 |
| E.164 | ITU-T numbering plan: `+` followed by country code and national number, for example `+8613800138000`. The canonical format for routing here. | ITU-T E.164 |
| iFC (initial Filter Criteria) | Rules on the S-CSCF that decide which AS a session is triggered to over ISC. | 3GPP TS 24.229 |
| IMS (IP Multimedia Subsystem) | The operator's SIP-based multimedia core: P-/I-/S-CSCF, HSS, AS, MRF. | 3GPP TS 23.228 |
| ISC (IMS Service Control) | The reference point between the S-CSCF and an AS. | 3GPP TS 24.229 |
| MRF (Media Resource Function) | Provides announcements, conferencing and transcoding. Not used: this POC is signalling only. | 3GPP TS 23.228 |
| Next hop | The peer the AS originates the outbound INVITE towards; selected by priority, with failover to the next one in the list. | — |
| Number translation | Rewriting a number between formats, for example E.164 `+8613800138000` to national `013800138000`. | — |
| P-Asserted-Identity | Header carrying the asserted identity of the originating user on a trusted trunk. | RFC 3325 |
| Redirect server | A SIP server that answers with `3xx` instead of relaying. Explicitly **not** implemented here. | RFC 3261 section 6 |
| Request-URI | The SIP URI a request is addressed to; the AS rewrites it with the translated number. | RFC 3261 section 8.1.2 |
| S-CSCF (Serving CSCF) | The IMS registrar and session controller that triggers ASs via iFC. Mocked here. | 3GPP TS 23.228 |
| SDP (Session Description Protocol) | The body that describes media. Passed through verbatim in this POC. | RFC 4566 |
| S-SBC (Service-SBC) | The operator's session border controller on the service side: it impersonates an internal AS towards the S-CSCF and a core node towards us. Mocked here. | — |
| Short code | A short service number such as `110`, `10086` or an office extension `6xxx`. | — |
| SIP trunk | A SIP relationship between two administrative domains; here between the operator's S-SBC and us. | — |
| Transaction | A request with its responses and retransmissions; the layer sippy manages for us. | RFC 3261 section 17 |
| UA / UAC / UAS | User Agent / the side that originates a request / the side that answers it. | RFC 3261 section 6 |
| User part | The part of a SIP URI before the `@`; it carries the number the AS translates. | RFC 3261 section 19.1 |
