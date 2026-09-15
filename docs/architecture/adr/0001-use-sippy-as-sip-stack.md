# ADR-0001: Use sippy as the SIP stack and B2BUA framework

- **Status:** Accepted
- **Date:** 2026-09-15
- **Deciders:** project maintainer
- **Related:** §4.5 (ADR requirement), §6 (tech stack), `docs/specs/index.md`

## Context

The AS must act as a SIP B2BUA: terminate an INVITE arriving on the trunk, apply number
translation and routing, then originate a new INVITE towards the S-SBC. That requires an
RFC 3261 stack with transaction state on both call legs.

Candidates considered:

| Option | Assessment |
| --- | --- |
| Self-written asyncio SIP stack | Full control and full visibility, but requires implementing the transaction layer, retransmissions and timers ourselves — effort and risk concentrated in protocol plumbing rather than in the service |
| pjsua2 (PJSIP binding) | Mature and complete, but adds a C/C++ dependency, a heavy callback model and a black box that is hard to debug and explain |
| aiosip / similar lightweight libraries | Fast to start, but maintenance status is unclear and complex transaction behaviour is where they tend to break |
| **sippy** | Pure Python, RFC 3261 compliant, mature B2BUA framework, explicit extension point for call control logic |

## Decision

Use **sippy 2.4.2** (BSD-2-Clause) as the SIP stack and B2BUA framework, installed with
`pip install sippy`. The AS is a sippy application whose business logic is a custom
**Call Control Logic** (a `CallController` with an answering UA and an originating UA);
the number translation and routing decision is applied where the event passes between
the two legs. The mock S-SBC uses the same stack, so both ends share identical protocol
behaviour.

## Verified facts (measured on this machine, 2026-09-15)

These were obtained by inspection and by an actual installation, not from memory. They
are recorded because they are expensive to re-derive.

- PyPI `sippy` latest is **2.4.2**, released 2026-07-15; source distribution only; the
  release artefact was built with CPython 3.13. The package declares **no
  `requires-python`**, so the Python version is our choice, not the package's.
- Dependencies pulled in: `ElPeriodic>=1.1`, `rtpsynth>=1.3.0`, `g722>=1.2.3`,
  `pycryptodome`, `websockets`, `flask`, `flask-login`. Media- and web-related
  dependencies come along even though this service does no media work and ships no web
  UI of its own.
- Installation on **Python 3.10.12** succeeds; `rtpsynth` (1.3.3) and `g722` (1.2.8)
  have prebuilt wheels, so no compiler toolchain is needed.
- Programming model (from `sippy/b2bua_simple.py`, 153 lines, the reference skeleton):
  - `CallController.recvEvent(event, ua)` relays events between `uaA` (answering UA) and
    `uaO` (originating UA) — **this is the hook for our business logic**.
  - `CallMap.recvRequest(req, sip_t)` is the entry point for incoming requests; it
    creates a `CallController` per new dialog.
  - `SipTransactionManager(global_config, cmap.recvRequest)` owns transactions.
  - `ED2.loop()` (`sippy.Core.EventDispatcher`) **blocks the calling thread** and is the
    main loop of the process.
- Package layout confirms availability of the primitives we need: `SipMsg`,
  `SipRequest`, `SipResponse`, `SipTransactionManager`, `UA`, `CCEvents`, `SipURL`,
  `SipPAssertedIdentity`, `SdpBody`, `UaStateConnected`, and others.
- Console entry points shipped: `b2bua_simple`, `b2bua`, `b2bua_radius`.

## Consequences

- **Blocking event loop.** `ED2.loop()` occupies the main thread, so the AS cannot share
  a thread or an asyncio loop with the console. This is why the console is a separate
  process talking to the AS over an internal API (see ADR-0002).
- **Extra dependencies.** Media and web libraries are installed but unused. Accepted;
  noted in the production gap register if it ever matters.
- **Behaviour must be observed, not assumed.** When sippy's behaviour is unclear, write
  a probe under `tools/` or `tests/` and run it. Documentation for the library is thin,
  so the source and real traffic are the references.
- **Version pinned.** sippy stays at 2.4.2; upgrading is a decision for the maintainer.
