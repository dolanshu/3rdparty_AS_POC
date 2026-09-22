# ADR-0011: Vendored third-party frontend libraries permitted

- **Status:** accepted
- **Date:** 2026-09-22
- **Related:** `docs/phase3-plan.md` (P13, D-P3-4) ·
  `docs/requirements/functional-and-nonfunctional.md` (REQ-F-050) ·
  ADR-0002 (console as separate process) ·
  `AGENT.md` §4.4 (amended by this ADR)

## Context

**AGENT.md §4.4** (inherited from Phase 1) says the console UI must use
**plain HTML/CSS/JS with no third-party front-end libraries**. The original
reasoning was twofold:

1. **Offline reliability.** The demo must run on an air-gapped machine. No CDN
   fetch at load time.
2. **No build step.** The console is a single Python file serving an inline HTML
   string. Adding npm or a bundler would expand the toolchain for a POC.

Phase 3-P13 introduces the **Enhanced Console** — a real-time operations
dashboard with live call-count line charts, state-distribution pie charts, and
a capacity gauge. Implementing these in hand-rolled SVG + `requestAnimationFrame`
is possible but would constitute a mini chart library of our own: axis scaling,
label layout, tooltip positioning, animation interpolation, responsive resize
handling, and state-distribution pie-slice geometry. That is thousands of
lines of UI code for one feature.

## Decision

**The console may vendored a single front-end library — Chart.js UMD bundle
(`chart.umd.min.js`, ~16 KB minified) — served from `/static/`.**

The rule change is narrow:

- **What is permitted.** Exactly one library, vendored locally, for charts
  only. Selection is Chart.js 4.x UMD because it is small, dependency-free,
  MIT-licensed, and widely used for exactly these three chart types.
- **What is still forbidden.** CDN references, npm, any build step (rollup,
  vite, webpack), any framework (React, Vue, Svelte), any UI component
  library. The console stays a single FastAPI process serving one HTML page
  with inline CSS and inline application JavaScript.
- **Governance.** Adding a new vendored library requires a new ADR. The
  inventory lives in `AGENT.md` §4.4 (amended by this record).

## Consequences

### Good

- P13 delivers three real charts (line, pie, gauge/doughnut) in ~100 lines of
  frontend JS instead of ~1000. The project stays focused on the SIP/AS
  domain, not on charting infrastructure.
- Offline demo is preserved. The bundle lives in `src/console/static/`,
  committed to the repository, served by FastAPI's `StaticFiles` mount. No
  network access needed at runtime.
- No build step. Chart.js UMD is a single file dropped in; the console stays
  "one `main.py` + one static dir".
- MIT license is permissive and compatible with the project's Apache-2.0.

### Bad / accepted cost

- One vendored binary-ish file (`chart.umd.min.js`, minified, ~16 KB) in the
  repository. It is not reviewable line-by-line. Mitigation: the file is
  sourced from the official Chart.js release on jsDelivr (CDN of the npm
  package), its checksum can be verified against the npm registry, and its
  license is copied alongside it (`chart.umd.min.js.LICENSE.txt`).
- AGENT.md §4.4's "no third-party front-end libraries" rule is no longer
  absolute. Mitigation: the rule is amended to "vendored, local-only,
  ADR-approved, chart-library-only" rather than open-ended permission.

## Alternatives considered

### Option A — Hand-rolled SVG charts (original plan before this ADR)

Draw everything in SVG with `setInterval` updates. **Rejected** because
implementing even basic features (y-axis auto-scaling with nice round numbers,
pie-slice geometry with label positioning, tooltip placement, rolling window
data management with `shift()`/`push()`) would be a substantial side project.
The POC's value is in the AS and the load generator, not in proving we can
write a chart library.

### Option B — Pull Chart.js from a CDN at runtime

`<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js">`.
**Rejected** because it breaks the offline demo guarantee (D-P3-3,
REQ-NF-010's spirit). An offline reviewer opening the console page would see
blank chart areas.

### Option C — npm + vite build step

Set up a real frontend project under `console-ui/`. **Rejected** because it
adds a build toolchain, a second package manager, and a bundler configuration
surface — all for one page. Against the POC "minimum viable toolchain"
principle.

## Reference

- Chart.js 4.x: https://www.chartjs.org/
- MIT license: https://github.com/chartjs/Chart.js/blob/master/LICENSE.md
- UMD bundle: https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js
