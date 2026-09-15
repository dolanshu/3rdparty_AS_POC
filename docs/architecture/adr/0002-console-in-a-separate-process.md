# ADR-0002: Run the console in a separate process behind an internal API

- **Status:** Accepted
- **Date:** 2026-09-15
- **Deciders:** project maintainer
- **Related:** ADR-0001, `AGENT.md` section 5 and 6, `docs/architecture/lld.md` section 5

## Context

The console has to show the live message flow, the rule that matched and the counters.
That means a web server (FastAPI + uvicorn, asyncio) has to live next to the SIP stack.

sippy runs its **own blocking event loop**: `ED2.loop()` occupies the thread that calls
it, and `AGENT.md` section 6 forbids sharing that thread or an asyncio loop with
anything else. Options considered:

| Option | Assessment |
| --- | --- |
| Serve the console from the sippy thread | Impossible without either blocking the loop or interleaving two event loops; a slow client would stall call processing |
| Run an asyncio loop in a second thread of the AS process | Works mechanically, but couples two failure domains: a console crash takes the B2BUA down, and every shared object needs locking |
| **Separate process with an internal API** | Clean failure isolation; the AS keeps a single-threaded, blocking design; the console can be restarted independently |

## Decision

The console is a **separate process** (`src/console/`) that reaches the AS only through
its internal API:

- `GET /healthz` — liveness and readiness
- `GET /api/v1/metrics` — counters, dispositions, rule hits, peer status
- `GET /api/v1/rules` — the active rule set, read-only
- `GET /api/v1/traces`, `GET /api/v1/traces/{call_id}` — Call-ID keyed traces
- `WS /ws/events` — live event feed

Address and port come from `INTERNAL_API_ADDRESS` / `INTERNAL_API_PORT`. The console
never imports AS modules and the AS never imports console modules.

## Consequences

- **Failure isolation.** The console can be restarted without touching calls, and a
  broken console cannot take the trunk down.
- **An extra interface to maintain.** The API is a contract; the payload shapes live in
  `src/as_app/internal_api.py` and are covered by unit tests.
- **Serving the API from the AS needs care.** The AS process is single-threaded, so the
  HTTP surface must not run inside the sippy thread; it is served from a thread that
  only reads snapshots (counters and traces are lock-guarded).
- **Deployment has three services** instead of two; see `docs/operations/deployment.md`.

## Gaps accepted

- No authentication on the internal API; it binds to the loopback address by default and
  is a demo surface. Registered in `docs/production-gaps.md`.
- The API is not versioned beyond `v1` and has no rate limiting.
