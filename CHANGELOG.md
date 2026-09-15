# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). One
version node per milestone; the milestone tag is `v<version>-m<n>`.

## [Unreleased]

## [0.1.0] — 2026-09-15 — M0 Foundation

### Added

- Repository skeleton per `AGENT.md` section 5: `config/` `deploy/` `docs/` `src/`
  `tests/` `tools/` and the meta files (`VERSION`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `NOTICE`, `LICENSE`, `Makefile`, `.env.example`,
  `.gitignore`).
- Toolchain: `pyproject.toml` (Python 3.10, sippy 2.4.2) with a committed `uv.lock`;
  `ruff` (format + lint), `mypy` and `pytest` configured in `pyproject.toml`. The three
  packages under `src/` are installed editable, so `uv sync` alone is enough to run
  `python -m as_app.main`.
- CI workflow `.github/workflows/ci.yml` running the gates in layers: lint, type check,
  unit, integration, e2e; the lock file is verified with `uv sync --frozen`.
- Documentation baseline per `AGENT.md` section 4.2: documentation map, SRS
  (`REQ-F-*`, `REQ-NF-*`), HLD, LLD, ADR-0001 … ADR-0006, operations guides
  (deployment, runbook, troubleshooting), acceptance criteria and report template,
  demo script, glossary and the production gap register.
- Sample office routing data (17 rules, 6 next hops) in `config/routing_rules.yaml` with
  the Pydantic model, loader and reload detection in `src/as_app/routing/`.
- `src/as_app/` skeleton: settings and startup self-check, error model, sippy adapter
  boundary, call controller hook, routing engine, structured logging, counters, per
  Call-ID tracing and the internal API payloads used by the console.
- `src/console/` and `src/s_sbc_mock/` process skeletons, `deploy/docker-compose.yml`
  with the three services and UDP ports, and `tools/` with the sippy probe, the rule
  viewer and the capture helper.
- `README.md` with positioning, architecture, quickstart, repository tour, non-goals and
  the documentation index.

### Verified

- sippy 2.4.2 installs and runs a minimal `SipTransactionManager` + `ED2.loop()` stack on
  Python 3.10.12: one INVITE in, `SIP/2.0 404 Probe` out, verdict line
  `minimal SipTransactionManager + ED2.loop() stack: OK`. The full probe output is
  recorded in `docs/acceptance/report.md`.
- All 12 M0 acceptance items executed; `uv sync --frozen`, `uv lock --check`,
  `ruff format --check`, `ruff check`, `mypy` and the three pytest layers are green
  (100 passed, 4 e2e cases skipped until M1).
- `make demo`, `make probe`, `make lint`, `make test` verified; graceful shutdown on
  `SIGTERM` logs `shutdown complete`; the console process answers `GET /healthz`;
  `docker compose -f deploy/docker-compose.yml config` validates (images not built).

### Notes

- `make demo` is still a stub: it shows the active rule set and states that the call demo
  lands in M1. The e2e cases are declared and skipped for the same reason.
