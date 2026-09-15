# Requirements (SRS)

Capability list for the third-party Application Server POC. Every requirement is
traceable to an acceptance item in `docs/acceptance/criteria.md` and to the design in
`docs/architecture/hld.md` / `lld.md`. Behaviour changes must walk this chain
(`AGENT.md` section 13).

Status values: `planned` — not implemented yet · `partial` — partly in place ·
`done` — implemented and covered by an acceptance item.

## 1. Functional requirements

| ID | Requirement | Status | Milestone | Acceptance |
| --- | --- | --- | --- | --- |
| REQ-F-001 | The AS listens for SIP requests on the configured UDP address and port (`SIP_LISTEN_ADDRESS` / `SIP_LISTEN_PORT`) and accepts INVITE from the trunk. | partial (socket prerequisites and self-check in place; stack in M1) | M0→M1 | ACC-M0-005, ACC-M1-001 |
| REQ-F-002 | The AS behaves as a B2BUA only: it terminates the incoming INVITE and originates a new INVITE towards the next hop. Redirect mode (`302`) is not implemented. | planned | M1 | ACC-M1-001 |
| REQ-F-003 | The called number is translated according to the declarative rule set: E.164 ↔ national `0…`, short codes, international `00…`. | partial (engine done, applied to the Request-URI in M2) | M0→M2 | ACC-M0-004, ACC-M2-001 |
| REQ-F-004 | A routing decision selects a next hop by priority and fails over to the next hop in the list. | partial (selection done, failover in M2) | M0→M2 | ACC-M0-004, ACC-M2-002 |
| REQ-F-005 | Rules are declarative YAML data under `config/`, validated on load and reloaded when the file changes (ADR-0004). | done | M0 | ACC-M0-004, ACC-M0-006 |
| REQ-F-006 | Error branches: no matching rule → `404`; policy rejection → `603`; caller abandons → `CANCEL`. | partial (decisions and mapping done, SIP behaviour in M1/M2) | M0→M2 | ACC-M2-003 |
| REQ-F-007 | A request from a source address outside `ALLOWED_PEERS` is rejected with `403` and `AS-PEER-001`. | partial (check implemented, applied in M1) | M0→M1 | ACC-M1-003 |
| REQ-F-008 | SIP headers and the SDP body are passed through unmodified; only the Request-URI and the number format are rewritten. | planned | M1 | ACC-M1-002 |
| REQ-F-009 | A complete call is driven: `INVITE → 100 → 180 → 200 OK → ACK → BYE`. | planned | M1 | ACC-M1-001 |
| REQ-F-010 | Every log line carries timestamp, level, module, `call_id`, `direction`, `peer` and an event message. | done | M0 | ACC-M0-007 |
| REQ-F-011 | Counters for calls, dispositions, error codes, rule hits and peer status; health endpoint; graceful shutdown on `SIGTERM`/`SIGINT`. | partial (counters and shutdown in place, HTTP surface in M3) | M0→M3 | ACC-M0-007, ACC-M3-002 |
| REQ-F-012 | Console shows the live message flow, the rule that matched, the configuration, statistics and an SVG topology; rules are read-only. | planned | M3 | ACC-M3-001 |
| REQ-F-013 | All configuration comes from the environment; switching from the mock to a real S-SBC is a configuration change only. | done | M0 | ACC-M0-005 |
| REQ-F-014 | Startup self-check (configuration schema, rules parse and validation, port availability, peer sanity) and fail-fast on invalid configuration. | done | M0 | ACC-M0-005 |
| REQ-F-015 | An internal error model maps `AS-*` codes to SIP status codes and log messages. | done | M0 | ACC-M0-007 |

## 2. Non-functional requirements

| ID | Requirement | Status | Milestone | Acceptance |
| --- | --- | --- | --- | --- |
| REQ-NF-001 | Signalling only: no RTP, no media anchoring, no MRF (ADR-0006). | done | M0 | ACC-M0-008 |
| REQ-NF-002 | UDP is the only transport; TCP and TLS are not implemented (ADR-0003). | done | M0 | ACC-M0-008 |
| REQ-NF-003 | Python 3.10 and sippy 2.4.2, pinned; the stack is verified by running it, not by assumption. | done | M0 | ACC-M0-002 |
| REQ-NF-004 | Routing and translation are pure functions with no sockets, no global state and no clock, tested by the unit layer; three test layers are green. | done | M0 | ACC-M0-009 |
| REQ-NF-005 | Every log line and console event is correlated by the SIP Call-ID. | partial (log and trace in place) | M0→M3 | ACC-M0-007 |
| REQ-NF-006 | No secrets, certificates or real traffic captures are committed; payload logging is explicit and off by default. | done | M0 | ACC-M0-010 |
| REQ-NF-007 | The repository reads as a telecom-grade deliverable: skeleton, documentation set, ADRs, acceptance evidence and production gap register (AGENT.md section 4). | done | M0 | ACC-M0-001, ACC-M0-003 |
| REQ-NF-008 | A clean checkout runs: `uv sync` → `make lint` / `make test`; the demo runs from `docker compose`. | done | M0 | ACC-M0-002, ACC-M0-009 |
| REQ-NF-009 | No performance or capacity claims: no call rate, latency or capacity target is defined for the POC. | done | M0 | ACC-M0-011 |
| REQ-NF-010 | Console uses no third-party front-end libraries and no build step. | done | M0 | ACC-M3-001 |

## 3. Traceability notes

- `REQ-F-003` and `REQ-F-004` are implemented as pure functions in
  `src/as_app/routing/engine.py`; the sippy glue that applies them to a Request-URI is M2.
- `REQ-NF-009` is a deliberate non-goal, registered in `docs/production-gaps.md`.
- Every requirement above is owned by a milestone; a requirement whose milestone has not
  been delivered is `planned` or `partial` by definition.
