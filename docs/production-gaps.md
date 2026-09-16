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

## Additional gaps registered while building M3

| Area | POC behaviour | Production requirement |
| --- | --- | --- |
| Console event feed | `WS /ws/events` polls the `TraceRecorder` at a fixed 1-second interval and pushes new call traces as JSON batches | Event-driven pub/sub: the recorder pushes events as they are recorded, with backpressure handling and per-client filtering |
| Console browser verification | The console page is fetched by an integration test but never driven by a real browser | Automated browser testing (e.g. Playwright) against a live call to verify real-time rendering, WebSocket connection and UI behaviour |
| Console versioning | The console process reports `version: "0.1.0"` on its own health endpoint, independent of the AS version | Consistent version reporting across all three services, or a shared version source |

## Additional gaps registered while building M4

| Area | POC behaviour | Production requirement |
| --- | --- | --- |
| Version discovery | The AS runtime version (`as_app.__version__`) is read from the repository `VERSION` file through a path relative to `src/as_app/__init__.py` (the M4 fix). This assumes a source checkout: an installed wheel does not carry `VERSION`, so the runtime falls back to `0.0.0+unknown`. | Derive the version from installed package metadata (`importlib.metadata.version("third-party-as-poc")`), or ship `VERSION` as package data. **Follow-up after M4.** |
| Closing a transaction manager mid-retransmission | `SipTransactionManager.shutdown()` cancels its own `cp_timer` but **not** the per-transaction retransmission timers (`t.teA`). A pending `timerA` can fire after shutdown and dereference the now-`None` `global_config`, raising `TypeError` in `transmitData`. This touches the AS `SIGTERM` graceful-shutdown path (a transaction still retransmitting when the process exits), and it is the root cause of a rare (~1 in 6 full-suite runs) non-deterministic test failure of `test_next_hop_failover_uses_the_second_hop`, where the in-process tests share one process-wide `ED2` loop. | Cancel every outstanding transaction timer on shutdown and drain in-flight transactions before exit. Fix **DEFERRED**: after M4, in a separate conversation, at the maintainer's instruction. The POC never shuts down while a transaction is mid-retransmission, so the observed impact is limited to the test suite and to the untested shutdown corner case. |

## Notes

- Gaps are never "forgotten features": each one is a decision with an ADR or a row in this
  table. `ADR-0003` (UDP only), `ADR-0006` (signalling only) and the M3 console gaps
  (poll-based event feed, no browser verification) are the largest.
- When a milestone closes a gap, move the row out of this table into `CHANGELOG.md` and
  record which acceptance item covers the new behaviour.
