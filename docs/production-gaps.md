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
| Console versioning | The console process reports `version: "0.1.0"` on its own health endpoint, independent of the AS version (the AS version is derived from `VERSION`, corrected in M4) | Consistent version reporting across all three services, or a shared version source |

## Additional gaps registered while building M4

| Area | POC behaviour | Production requirement |
| --- | --- | --- |
| Version discovery | **Resolved by P5.** The AS runtime version (`as_app.__version__`) is resolved by a three-step chain: `importlib.metadata.version("third-party-as-poc")` first, then the repository `VERSION` file (relative to `src/as_app/__init__.py`, the M4 fix), then `0.0.0+unknown`. An installed wheel no longer reports `0.0.0+unknown` because it carries distribution metadata even though it ships no `VERSION` file. **Remaining caveat:** the chain still needs the distribution metadata to be present and readable — a wheel installed without its metadata (or a vendored/`zipapp` copy of `src/as_app` with neither metadata nor `VERSION`) still falls through to `0.0.0+unknown`. Shipping `VERSION` as package data would close that last case; it is not needed for any supported install path. | Version reporting should not depend on where the code is installed from: derive it from the installed distribution metadata, and keep the `VERSION` file (or package data) only as the source-checkout fallback. |
| Closing a transaction manager mid-retransmission | **Resolved by P8a (2026-09-18).** sippy's `SipTransactionManager.shutdown()` still cancels only its own `cp_timer`; the repository now cancels what it armed first, in `as_app.sip_adapter.cancel_transaction_timers`, before handing the manager to sippy. Historical defect, kept for the record: a pending `timerA` used to fire after shutdown and dereference the then-`None` `global_config`, raising `TypeError: 'NoneType' object is not subscriptable` in `transmitData`. It hit the AS graceful-shutdown path (a transaction still retransmitting when the process exits) and it was the root cause of the rare (~1 in 6 full-suite runs) non-deterministic failure of `test_next_hop_failover_uses_the_second_hop`, where the in-process tests share one process-wide `ED2` loop. | Cancel every outstanding transaction timer on shutdown and drain in-flight transactions before exit. **Remaining caveat:** sippy itself is untouched — a third-party `SipTransactionManager` is still shutdown-dependent, and anything this repository arms outside `AsStack.stop()` has to be cancelled by whoever owns it. In-flight transactions are cancelled, not **drained**: no final response is sent to a peer for a transaction that was still retransmitting, so a far end that was mid-call sees silence rather than an error, which a production node would answer with a `503` / retry-after policy. |

## Additional gaps registered while building P1 (compose demo)

| Area | POC behaviour | Production requirement |
| --- | --- | --- |
| Rule set per environment | The trunk address lives in the rule set, because the AS originates the second leg to the hop `action.next_hops` selects and the routing engine resolves that name against the file's own `next_hops` catalogue. `SBC_PEER_ADDRESS` does not rewrite it. The POC therefore ships **two** rule files that differ only in the catalogue addresses: `config/routing_rules.yaml` (`127.0.0.1`, local runs) and `config/routing_rules.compose.yaml` (`172.28.0.3`, the compose network). The rule bodies are duplicated by hand and can drift. | One rule set per deployment with the peer addresses supplied by the environment — e.g. let a catalogue `address` be written as `${SBC_PEER_ADDRESS}` and expand it at load time (the SRS already makes all configuration environment-based, `AGENT.md` section 8). A managed configuration service would separate the dial plan (rules) from the peer inventory (addresses) entirely. |
| Rule set drift between environments | Nothing detects that the two POC rule files have diverged; only review catches it. | Validate every environment's rule set against one canonical source (generate, or schema-check that they differ only in the address fields). |
| Build-time package index | The Dockerfiles accept an optional package-index build argument (`PIP_INDEX_URL` / `UV_DEFAULT_INDEX`, so a build behind a slow or filtered network works). A non-default index makes uv re-resolve inside the image — a build-time, image-local `uv.lock` rewrite that keeps the pinned versions but re-resolves them from that index. The committed `uv.lock` always stays on public PyPI. | Build in an environment with the canonical index (or a mirror that is guaranteed identical), and verify the image with a reproducible provenance/SBOM step rather than trusting a build-time re-resolution. |

## Notes

- Gaps are never "forgotten features": each one is a decision with an ADR or a row in this
  table. `ADR-0003` (UDP only), `ADR-0006` (signalling only) and the M3 console gaps
  (poll-based event feed, no browser verification) are the largest.
- When a milestone closes a gap, move the row out of this table into `CHANGELOG.md` and
  record which acceptance item covers the new behaviour.
