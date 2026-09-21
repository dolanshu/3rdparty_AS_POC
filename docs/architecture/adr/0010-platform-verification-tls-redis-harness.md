# ADR-0010: Platform verification — second transport, second state store and a capacity harness

- **Status:** Accepted
- **Date:** 2026-09-20
- **Deciders:** project maintainer
- **Related:** `docs/phase2-plan.md` section 2 (D3, D9, D10) and section 3 (P11), section 5.1 ·
  `docs/requirements/functional-and-nonfunctional.md` (REQ-F-034…REQ-F-037, REQ-NF-022…REQ-NF-026) ·
  ADR-0001 (sippy) · ADR-0003 (UDP only — superseded by this ADR, see decision 5) ·
  ADR-0009 (decision 5 — no second implementation in P10) ·
  `docs/architecture/hld.md` section 10 · `docs/architecture/lld.md` section 11.4 ·
  `docs/production-gaps.md` (rows "Transport", "Cross-call anti-fraud state", "Capacity") ·
  `AGENT.md` sections 6, 9, 10

## Context

P10 extracted the AS skeleton into the `as_platform` library and left two pluggable seams —
Transport and StateStore — each with exactly one implementation (UdpTransport and
InMemoryStateStore). P10 deliberately did not add a second implementation or a load harness
(decision 5, REQ-NF-020), because D3 and D10 frame those as **verification outputs** — things
that run *after* the abstraction to prove it was right, not inputs that would teach the
abstraction what to support.

P11 is that verification step. It adds a second implementation behind each seam plus a
first-class capacity harness — three items that together prove the abstraction holds. D3
names TLS and an external state store as the two pluggable dimensions that matter because
they exercise different kinds of boundary:

- **Transport** tests the socket seam — the gap between the sippy event loop and what the
  stack listens on — and asks whether the platform handles a fundamentally different I/O
  model correctly.
- **State store** tests the storage seam — the gap between the cross-call data structures
  the anti-fraud use case owns and where they are kept — and asks whether the platform
  handles an I/O-bound boundary correctly (Redis blocks) without violating `AGENT.md section 6`
  (the sippy loop must not block).
- **Capacity harness** is not a seam; it is a measurement capability. It turns P9.5's
  read-only probe into a first-class library component that any AS application can consume.

P11 has three design-stage probes to settle before any code moves:

1. **Does sippy support SIP TLS?** (`AGENT.md section 14` forbids assuming). The answer determines
   whether a `TlsTransport` is a thin wrapper around sippy's TLS server or a bridge outside
   sippy.
2. **Does sippy support TCP at all?** TCP is the usual prerequisite for SIP TLS
   (RFC 3261 section 18.1), so the probe checks TCP first.
3. **What does a Redis-capable `StateStore` look like without blocking the sippy loop?**
   The rule-reload timer is the precedent: it is a loop-owned `Timeout` that polls a file
   outside the sippy callback.

## Verified facts

The probes were run on `2026-09-20` against sippy 2.4.2, pinned by `AGENT.md section 6`:

**(a) sippy has no SIP TLS support.** `SipTransactionManager.newTransaction()` handles
only `udp`, `ws`, `wss` and raises `RuntimeError` on anything else (`SipTransactionManager.py`
L410-421). `SipConf` hard-codes `default_transport = 'udp'`. There is no `Tls_server` or
`Tcp_server` class — only `Udp_server`, `Network_server` (abstract base), `Wss_server`
(WebSocket Secure — TLS on WebSocket frames, not SIP), and `XMPP_server`. `SipURL` accepts
`sips:` scheme and `transport=tcp` / `transport=tls` in URIs, but `newTransaction()` rejects
them downstream.

**(b) sippy has no TCP transport either.** Same code path — `transport = 'tcp'` hits the
`RuntimeError` branch. The only transport values `newTransaction()` accepts are the three
above.

**(c) `Wss_server` does use TLS — for WebSocket only.** `Wss_server.py` L30-61 imports
`ssl.SSLContext`, loads `certfile` and `keyfile` into a `PROTOCOL_TLS_SERVER` context, and
passes it to `websockets.serve()`. This is WebSocket Secure (RFC 7118), not SIP over TLS
(RFC 3261 section 26.2). The sippy side of WSS terminates SIP messages into WebSocket
frames and reassembles them; both sides need WebSocket endpoints.

**(d) sippy's transport init is hard-wired to UDP.** `SipTransactionManager` initializes
with `model_udp_server = (Udp_server, Udp_server_opts)` (L254) and passes that tuple to
`local4remote`, which creates exactly one UDP server. There is no configuration flag that
switches to a different server class.

**(e) The Transport seam as designed by P10 is wide enough.** `Transport.sip_config()`
returns `global_config` keys — `UdpTransport` returns `_sip_address` and `_sip_port` — and
`BaseAsStack.start()` spreads those keys into sippy's config dict. A TLS bridge needs
different keys (a local UDP port sippy binds to, plus TLS listener configuration) and can
return them from `sip_config()` without sippy learning the difference. The bridge itself
lives **outside** sippy, so sippy's hard-wired UDP init never knows TLS exists.

**(f) The StateStore protocol is narrow enough.** `StateStore` exposes `read`, `write` and
`trim`. `RedisStateStore` needs the same signatures and must bridge the blocking Redis
client to sippy threads. The rule-reload precedent — a loop-owned `Timeout` that runs a
poll function — shows sippy's event loop is the right place to schedule work; a dedicated
worker thread handles the actual Redis I/O.

## Decisions

### Decision 1 — TLS transport is an external bridge, not a sippy subclass

`TlsTransport` terminates TLS/SIPS connections at the Transport seam layer with a Python
`ssl` + `socket` listener. It binds its TLS listener to a configured port (typically 5061),
creates a paired **local UDP socket** on a different port, and bridges encrypted SIP
messages ↔ decrypted SIP messages across the gap. `SipTransactionManager` binds to the
local UDP port and talks UDP internally — sippy's UDP machinery is untouched.

**Why a bridge and not a sippy subclass.** Modifying sippy is forbidden by `AGENT.md section 6`,
and subclassing sippy to add a `Tls_server` class would require touching
`SipTransactionManager.newTransaction()` (the transport selector) and `local4remote`
(the UDP server init) — both are sippy internals, not extensions. Even if those files were
fair game, a `Tls_server` would be more than just "open a TLS socket": it would need
record-keeping for each TLS connection, handling of the STARTTLS handshake if we went that
route, and changes to the UAC path where sippy originates outbound requests. The bridge
avoids all of that: it uses Python's standard `ssl` module, its TLS listener is a normal
file descriptor, and the sippy side sees only a UDP socket on localhost.

**Why this is honest.** Terminating TLS outside the AS is a real deployment pattern: load
balancers, SIP proxies and S-SBCs routinely terminate TLS and forward SIP over UDP to the
AS. This is not a hack — it is what operators actually do, and it proves the Transport
seam is pluggable without pretending sippy supports what it does not.

### Decision 2 — `NextHop.transport` extends to `Literal["udp", "tls"]`

The `NextHop` value object (ADR-0009 decision 2) currently pins `transport: Literal["udp"]`
because UDP is the only sippy supports. P11 extends it to `Literal["udp", "tls"]`. This
makes the B2BUA relay direction configurable: an AS instance can originate an outbound
INVITE towards a TLS-capable peer (the relay goes through `TlsTransport` on the originating
side) or towards a UDP peer. The extension is purely additive — existing `"udp"` values
keep working unchanged.

### Decision 3 — Redis state store uses a background-worker queue, not synchronous calls

`RedisStateStore` preserves the `StateStore` protocol's synchronous-looking `read`,
`write` and `trim` signatures but implements them with a **background-worker queue**:

- `read(key)` and `write(key, value)` enqueue work items and callers wait on a condition
  variable for the result.
- A dedicated worker thread runs a persistent Redis client and dequeues items.
- `trim(prefix, limit)` follows the same pattern.

The sippy callback **never blocks** — it only enqueues work. The worker thread performs
the Redis I/O and signals results back through the condition variable. This mirrors the
rule-reload precedent where sippy's loop-owned timer polls outside the callback; here the
"outside" is a thread pool rather than a timer, but the principle is identical.

`InMemoryStateStore` stays the default (D9). No environment variable or configuration is
required to run the in-memory store — it is what every `BaseAsStack` gets. Redis is wired
in only when an application's configuration explicitly selects it. `make demo`, the three
application test layers and CI keep running with no external service.

### Decision 4 — Capacity harness is a library component, not a benchmark

The harness lives in `as_platform.capacity_harness` (a new module). It exposes one primary
class — `CapacityDriver` — that takes an AS stack instance and drives it at configurable
offered concurrency levels:

- The driver calls `CallController.decide()` (or equivalent) directly, bypassing sockets,
  at increasing concurrency levels starting from 1 up to a caller-configured ceiling.
- At each level, it records how many calls completed within a configured timeout, how
  many timed out, and the event-loop gap (measured by scheduling a zero-delay `Timeout`
  and observing the actual latency).
- The driver does **not** emit numbers as "benchmarks". Its output is structured data
  passed back to the caller, logged as trace events, and optionally written to counters.

This is deliberate silence on absolute numbers (D10, REQ-NF-009). The harness is a
measurement capability — it answers "at what concurrency does degradation become
observable?" — not a performance claim. The harness itself is excluded from this
repository's acceptance evidence; what is recorded is the harness API surface and its
library-level tests.

### Decision 5 — ADR-0003 status changes to Superseded

ADR-0003 ("UDP only, no TCP and no TLS on the trunk") was accepted on `2026-09-15` when
UDP was the only transport sippy supports and the POC ran entirely on loopback. P11 ships
`TlsTransport` behind the pluggable seam, so the ADR's core decision is now replaced.
ADR-0003's status is changed to "Superseded by ADR-0010" in the implementation commit; the
existing consequences section remains accurate because `UdpTransport` is still the default
and TLS is optional. No Phase 1, P8, P9 or P10 behaviour changes.

## Consequences

- `as_platform` gains three new public classes and one new module:
  - `TlsTransport` in `as_platform.transport` (seam second implementation)
  - `RedisStateStore` in `as_platform.state_store` (seam second implementation)
  - `NextHop.transport` widened from `Literal["udp"]` to `Literal["udp", "tls"]`
  - `CapacityDriver` in a new `as_platform.capacity_harness` module
- The application repositories (`src/as_app/`, `src/anti_fraud_as/`) stay on `UdpTransport`
  and `InMemoryStateStore` by default; no application wiring changes at `make demo`.
- `docs/production-gaps.md` rows "Transport" and "Cross-call anti-fraud state" are
  partially closed: TLS and Redis are implemented as second options behind their seams,
  but the harness does not publish numbers (D10).
- `AGENT.md section 6` is not violated. No blocking I/O happens inside a sippy callback:
  TLS bridging is done by Python `socket`/`ssl` on the main sippy thread (non-blocking
  socket I/O is what `ED2` manages), and Redis I/O happens on a dedicated worker thread.
- Certificate handling follows `AGENT.md section 9`: self-signed certs are generated locally
  with an openssl script, gitignored, and never committed.
- ADR-0003's status field changes from "Accepted" to "Superseded by ADR-0010" in the
  implementation commit. No other ADRs change status.

## Gaps accepted

- **TLS bridge is not SIP TLS (RFC 3261 section 26.2) end-to-end.** A real SIP TLS trunk
  would require a TLS-capable SIP user agent (UAC) side — sippy still does not originate
  TLS requests, only terminates them at the AS. If the AS needs to relay towards a TLS peer,
  that path is not covered by this ADR (sippy's `newTransaction()` still rejects
  `transport='tls'`). This limitation is recorded in `REQ-NF-022` and is a production gap,
  not a hidden defect — the bridge covers the AS listening side, not the AS originating side.
- **WSS is not implemented as a transport option.** sippy supports WebSocket Secure,
  which is TLS-encrypted, but adding WSS as a third transport would require both sides
  (mock UAC/UAS and AS) to speak WebSocket frames. P11 does not add WSS.
- **Capacity harness does not measure end-to-end latency.** It drives through the
  controller callback interface, not over sockets, so round-trip time, retransmission
  behaviour and message-size effects are not captured. P9.5's read-only probe remains the
  closest thing to an end-to-end load measurement; the harness is a focused tool that
  trades realism for determinism.
