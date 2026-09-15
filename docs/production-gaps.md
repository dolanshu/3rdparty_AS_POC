# Production gap register

**Rule (`AGENT.md` section 3): every POC simplification must be registered here, not
silently ignored.** A change that deepens a shortcut without updating this register is an
incomplete change.

POC behaviour | production requirement | why it differs.

## Baseline (from `AGENT.md` section 3, registered in M0)

| Area | POC behaviour | Production requirement |
| --- | --- | --- |
| Transport | UDP only | UDP + TCP + TLS; TLS mandatory on public-internet trunks |
| Peer authentication | Source IP allowlist at most | IP allowlist + SIP Digest + TLS certificate (triple check) |
| Topology | Single peer, single trunk | Multiple S-SBC peers, failover routing |
| Core network | Mocked UAC/UAS in one process | Real S-CSCF, iFC triggering, subscription data |
| Header handling | Verbatim pass-through | Header normalisation, private extension stripping |
| Transactions | Happy path + a few error branches | Full RFC 3261 retransmission, timer and timeout handling |
| Reliability | Single process, no persistence | Restart safety, session recovery, watchdog |
| Media | None | SDP negotiation validation, optional media anchoring |
| Charging | None | CDR generation per call leg |
| Security | Local mock, dev-only | DoS protection, rate limiting, CAC, black/white lists |
| Observability | Console + log trace | Centralised collection, retention, alerting |
| Configuration | Local YAML + `.env.example` | Managed configuration service, secret manager |
| Capacity | Not measured | SLA-backed throughput and call setup latency |

## Additional gaps registered while building M0

| Area | POC behaviour | Production requirement |
| --- | --- | --- |
| Internal API | No authentication, bound to loopback, `v1` unversioned beyond the prefix | Authentication, TLS, rate limiting, versioned contract |
| Rule management | A YAML file edited by hand, reloaded by polling size and mtime | Managed configuration service with validation, approval workflow and audit trail |
| Rule failover | Next hop failover by priority within one rule | Health-checked peers, circuit breakers, per-peer capacity limits |
| Number normalisation | Prefix-based translation only | Full number plan (E.164 + national prefix tables), portability lookups (NPDB) |
| Emergency calls | Emergency short codes are routed like any other number | Location handling, PSAP routing, priority treatment, regulatory logging |
| Trunk addressing | Next hops are `127.0.0.1` ports so the demo runs offline | Real addresses with DNS/SRV resolution (RFC 3263) |
| Dependency footprint | sippy pulls in media libraries (`rtpsynth`, `g722`) that are never used | Trimmed dependencies, supply-chain review, SBOM |
| Time and clocks | Wall clock for log timestamps, monotonic for sippy timers | NTP-synchronised clocks, correlated timestamps across nodes |
| Data retention | Traces kept in memory, bounded to a few hundred calls | Durable trace store with retention policy and privacy controls |
| Testing | Tests run against the mock only | Interoperability testing against real S-SBC implementations |

## Notes

- Gaps are never "forgotten features": each one is a decision with an ADR or a row in this
  table. `ADR-0003` (UDP only) and `ADR-0006` (signalling only) are the two largest.
- When a milestone closes a gap, move the row out of this table into `CHANGELOG.md` and
  record which acceptance item covers the new behaviour.
