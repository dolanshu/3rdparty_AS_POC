# Security policy

## Scope

This repository is a **proof of concept**. It is not production software and must not be
deployed on a network that carries real subscriber traffic.

## What is deliberately not implemented

The following are known gaps, registered in `docs/production-gaps.md` and in ADR-0003 /
ADR-0006. Do not imply in documentation, logs or demos that they exist:

- **No TLS.** The trunk is UDP only; SIP over TLS is not implemented.
- **No SIP Digest authentication.** The only peer check is the source address allowlist
  configured with `ALLOWED_PEERS`.
- **No DoS protection.** No rate limiting, no call admission control, no black or white
  lists.
- **No media handling**, therefore no SRTP and no media-plane attack surface in this
  repository.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to the project maintainer, Dolan Shu
<dolan.d.shu@gmail.com>, rather than opening a public issue. Include:

- what you observed and where (component, version from `VERSION`),
- the steps to reproduce, using the local mock only,
- the impact you believe it has.

Never attach captures of real traffic, real subscriber numbers or real addresses — this is
explicitly forbidden by `AGENT.md` section 13.

## Handling of sensitive material

- No keys, certificates, tokens or real addresses are committed; only `.env.example` and
  generation scripts live in the repository.
- Payload logging is off by default (`LOG_PAYLOADS=false`); the console may display
  payloads, the log must not do so by default.
