# CI blockers for merging `phase3` into `main`

**Status: merge will go RED at the first gate.** Prepared 2026-09-26 against
`phase3` @ `d8b68a3`, merge-base with `main` = `c626175`. Every finding below was
produced by running the gate locally in this checkout, not by reading the workflow
and guessing.

**Why this document exists:** `push` to `phase3` does not trigger CI (`.github/workflows/ci.yml`
only listens on `branches: [main]`), so the branch has never been gated. These are the
failures that will surface the moment it lands on `main`.

Caveat: the local runs were made in a working tree with uncommitted edits to
`src/console/main.py` and `.env.example`. `src/console/main.py` accounts for 6 of the
ruff findings listed below, so counts may shift by a few — the *conclusions* do not.

---

## 1. Trigger behaviour after the merge

`.github/workflows/ci.yml` is **byte-identical on `main` and `phase3`** (`git diff main...phase3 -- .github/` is empty), so the merge itself introduces no workflow change.

| Event | Runs? |
| --- | --- |
| `push` to `phase3` | No — not in `branches:` |
| `pull_request` → `main` | Yes |
| `push` to `main` (the merge) | Yes |
| `workflow_dispatch` | Yes |

`paths-ignore: ['docs/**', '**.md']` **will not skip the run.** Of the 120 changed files,
54 are docs/markdown and **66 are not** (`src/`, `tests/`, `tools/`, `scripts/`,
`pyproject.toml`, `uv.lock`, `Makefile`). `paths-ignore` only skips when *every* changed
file matches, so all five layers run.

---

## 2. The five gates and what each one executes

Dependency chain: `lint` + `type-check` run in parallel, then `unit` → `integration` → `e2e`.
Each job does `checkout` → `git clone ../as_platform` → `uv sync --frozen`.

| Job | Command | Test items collected |
| --- | --- | --- |
| `lint` | `ruff format --check .` then `ruff check .` | — |
| `type-check` (display name `type`) | `uv run mypy` | — |
| `unit` | `pytest tests/unit -m unit -q` | **226** (39 deselected, see B3) |
| `integration` | `pytest tests/integration -m integration -q` | **49** |
| `e2e` | `pytest tests/e2e -m e2e -q` | **88** (65 need chromium, see B4) |

### unit — 226 items across 17 files

| File | Items |
| --- | --- |
| `test_repository_baseline.py` | 56 |
| `test_screening_data.py` | 23 |
| `test_screening_engine.py` | 22 |
| `test_fraud_error_model.py` | 18 |
| `test_routing_engine.py` | 16 |
| `test_caller_state.py` | 15 |
| `test_fraud_configuration.py` | 15 |
| `test_internal_api.py` | 12 |
| `test_sip_adapter.py` | 11 |
| `test_routing_rules.py` | 11 |
| `test_bootstrap.py` | 6 |
| `test_fraud_call_controller.py` | 5 |
| `test_errors.py` | 4 |
| `test_observability.py` | 4 |
| `test_ims_orchestrator.py` | 3 |
| `test_route_header.py` | 3 |
| `test_p12_call_controller.py` | 2 |

### integration — 49 items across 11 files

| File | Items |
| --- | --- |
| `test_fraud_screening_path.py` | 13 |
| `test_concurrent_load.py` | 7 |
| `test_console.py` | 7 |
| `test_translation.py` | 7 |
| `test_signalling_path.py` | 4 |
| `test_chained_topology.py` | 3 |
| `test_startup_self_check.py` | 3 |
| `test_call_trace_messages_api.py` | 2 |
| `test_call_trace_sequence.py` | 1 |
| `test_console_call_trace_flow.py` | 1 |
| `test_p12_call_events.py` | 1 |

### e2e — 88 items across 6 files

| File | Items |
| --- | --- |
| `test_console_dashboard.py` | 55 |
| `test_console_chained_dashboard.py` | 21 |
| `test_call_flows.py` | 5 |
| `test_demo_script_path.py` | 3 |
| `test_chained_call_flows.py` | 2 |
| `test_fraud_call_flows.py` | 2 |

---

## 3. Blockers

### B1 — `lint` fails, and it gates everything downstream

Because `unit` needs `[lint, type-check]` and the rest chain off `unit`, **a red `lint`
means the other three jobs never execute.** This is the first thing to fix.

```
ruff format --check .   →  30 files would be reformatted, 124 files already formatted
ruff check .            →  Found 67 errors (24 fixable with --fix)
```

`ruff check` by rule:

| Rule | Count |
| --- | --- |
| `E501` line too long | 21 |
| `F541` f-string without placeholders | 8 |
| `W605` invalid escape sequence | 6 |
| `I001` unsorted imports | 5 |
| `N806` non-lowercase variable in function | 4 |
| `E702` multiple statements on one line | 4 |
| `SIM105` use contextlib.suppress | 3 |
| `F401` unused import | 3 |
| `SIM102` / `N802` / `E701` / `B007` | 2 each |
| `UP035` / `SIM115` / `F841` / `C420` / `B011` | 1 each |

By file (only files with more than one finding listed):

| File | Findings |
| --- | --- |
| `tests/e2e/test_console_dashboard.py` | 19 |
| `tests/e2e/test_console_chained_dashboard.py` | 18 |
| `tests/e2e/conftest.py` | 7 |
| `src/console/main.py` | 6 |
| `tools/demo_chained_call.py` | 2 |
| `tools/chained_helpers.py` | 2 |
| `tools/chained_as_probe.py` | 2 |
| `tests/e2e/test_demo_script_path.py` | 2 |
| `src/ims_mock/chained_stack.py` | 2 |
| `tools/call_load_generator.py`, `tests/unit/test_route_header.py`, `tests/unit/test_fraud_call_controller.py`, `src/s_sbc_mock/uas.py`, `src/ims_mock/pcscf_relay.py`, `src/ims_mock/chain_config.py`, `src/anti_fraud_as/call_controller.py` | 1 each |

Fix:

```bash
uv run ruff check --fix .     # clears 24 of the 67
uv run ruff format .          # reformats the 30 files
uv run ruff check .           # then clear the remaining by hand
```

Note: `E501` is *not* waived for tests. Only `src/console/main.py` and
`docs/ocr-review-*.md` are excluded from it; `tests/**/*.py` is waived for `D` (pydocstyle)
only, so long lines in the new e2e files are real failures.

### B2 — `type` fails: 4 mypy errors

```
src/as_app/call_controller.py:175: error: Item "None" of "AbstractEventLoop | None" has no attribute "create_task"  [union-attr]
src/anti_fraud_as/call_controller.py:257: error: Item "None" of "AbstractEventLoop | None" has no attribute "create_task"  [union-attr]
src/as_app/main.py:198: error: "BaseCallMap" has no attribute "app"  [attr-defined]
src/anti_fraud_as/main.py:211: error: "BaseCallMap" has no attribute "app"  [attr-defined]
```

The first two are the same `get_event_loop()` returning `Optional` in both AS instances —
fix once per call site (assert, or capture the running loop where it is known non-`None`).
The last two are the same missing attribute on the sippy `BaseCallMap` in both `main.py`
files — likely needs a `# type: ignore[attr-defined]` with a comment, or an accessor,
depending on what `as_platform` exposes.

`mypy` is configured with `packages = ["anti_fraud_as", "as_app", "console", "s_sbc_mock"]`.
Note that **`src/ims_mock` (425 new lines in `chained_stack.py` alone) is not in the mypy
package list** and is therefore unchecked — worth adding deliberately if it is meant to be
covered.

### B3 — 39 new unit tests are silently skipped by `-m unit`

`-m unit` selects only marked tests. Three entirely-new phase 3 files carry **no marker at
all**, so all 39 of their tests are deselected without any failure being reported:

| File | Skipped items |
| --- | --- |
| `tests/unit/test_call_load_models.py` | 19 |
| `tests/unit/test_call_pool.py` | 12 |
| `tests/unit/test_generator_api.py` | 8 |

`tests/unit` holds 265 tests; CI runs 226. The 39 all pass locally
(`pytest tests/unit -q` → 265 passed in 11.3 s), so this is a coverage gap, not a failure —
and the quietest kind: the job goes green while a whole new subsystem is untested.

Fix — add a module-level marker to each of the three files (matching the convention used
elsewhere in the suite):

```python
pytestmark = pytest.mark.unit
```

`test_call_pool.py` already uses `@pytest.mark.asyncio` per test; a module-level
`pytestmark` composes with those. Consider also asserting the invariant in CI so this
cannot recur — e.g. run `-m unit` with `-p no:cacheprovider --strict-markers` plus a check
that collected + deselected equals the file total, or make the marker mandatory via a
conftest hook.

### B4 — 65 of the 88 e2e tests need a browser that CI never installs

The suite is parametrized `[chromium]` (via `pytest-playwright`) on 65 items. `uv sync`
installs the *Python* package `playwright==1.60.0`; it does **not** download the browser
binary. `.github/workflows/ci.yml` has **no `playwright install` step**, so every one of
those 65 will error with a missing-executable message.

Fix — add a step to the `e2e` job before `pytest`:

```yaml
      - name: Install the Chromium browser
        run: uv run playwright install --with-deps chromium
```

Also relevant: `tests/e2e/conftest.py` shells out to `lsof -ti :<port>` in `_kill_port`
(present on `ubuntu-latest`) and depends on `.venv/bin/python` existing at the repo root
(`VENV_PY`) — which `uv sync` does create. Both hold on the runner; no action needed.

### B5 — one integration test already fails

```
tests/integration/test_call_trace_sequence.py::test_completed_call_trace_has_invite_and_200_events
```

Local result: `1 failed, 48 passed` in 36.7 s. This is invisible today only because the
`lint` gate (B1) blocks `integration` from ever running. Expect it immediately after B1/B2
are fixed.

### B6 — `../as_platform` clone: the workflow comment is stale (verify before merge)

The header comment in `ci.yml` (lines 13–17) states the library "has NO remote configured
yet and has never been pushed" and that "CI is NOT green". That is no longer true locally:
`../as_platform` has `origin → git@github.com:dolanshu/as_platform.git`, and this repository
is `git@github.com:dolanshu/3rdparty_AS_POC.git` — the owner matches what
`github.repository_owner` will expand to, so the clone URL should resolve.

Two follow-ups, both already flagged as TODOs in the file:

1. Confirm the library is actually pushed, then **update the stale comment** in `ci.yml`.
2. Pin the clone ref. Every job uses `git clone --depth 1` at default HEAD, which drifts
   silently. Use the repo variable `AS_PLATFORM_REF` (see `ci.yml` lines 40–42).

---

## 4. Verified clean — no action needed

| Check | Result |
| --- | --- |
| `uv lock --check` | Passed (65 packages). `uv sync --frozen` will not fail on lock drift |
| `pytest tests/unit -q` (all 265) | 265 passed |
| `pytest tests/unit -m unit -q` | 226 passed, 39 deselected |
| `pytest tests/integration -m integration -q` | 48 passed, 1 failed (B5) |
| New dev deps `playwright`, `pytest-playwright`, `httpx2` | Present in `uv.lock`; `httpx2` is correct — `starlette/testclient.py:33` prefers `import httpx2 as httpx`, so it is a supported substitute, not a typo for `httpx` |
| `pyproject.toml` `pythonpath = ["src", "."]` | Needed by the new `tools/` tests; already in place |
| `tests/**/*.py` pydocstyle waivers | phase 3 widened `"tests/*" = ["D104"]` to `"tests/**/*.py" = ["D"]` — a loosening, so ruff failures are not docstring-related |

---

## 5. Suggested order

1. **B3** — add `pytestmark` to the three unmarked unit files (cheap, and restores real coverage).
2. **B4** — add the `playwright install` step to the `e2e` job.
3. **B1** — `ruff check --fix` + `ruff format`, then clear the remainder.
4. **B2** — the 4 mypy errors (two are duplicated across the two AS instances).
5. **B5** — `test_call_trace_sequence.py`.
6. **B6** — confirm `as_platform` is pushed, update the stale comment, pin `AS_PLATFORM_REF`.

Re-verify locally before merging:

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy \
  && uv run pytest tests/unit -m unit -q \
  && uv run pytest tests/integration -m integration -q \
  && uv run pytest tests/e2e -m e2e -q
```
