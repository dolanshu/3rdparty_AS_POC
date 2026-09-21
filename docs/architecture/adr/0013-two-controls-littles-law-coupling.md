# ADR-0013: Two load controls with Little's Law coupling — pool ceiling + refill throttle

- **Status:** Accepted
- **Date:** 2026-09-21
- **Deciders:** project maintainer
- **Related:** `docs/phase3-plan.md` (D6, P12 Stage 2) ·
  `docs/post-phase2-directions.md` Part B D6 ·
  `docs/requirements/functional-and-nonfunctional.md` (REQ-F-039) ·
  Maintainer's grill round 2 (2026-09-21) — explicit Little's Law question

## Context

The load generator (ADR-0012) needs interactive controls. The natural first thought
is a single slider: "call rate" — fire N calls per second, let concurrent calls emerge
as a side effect of `rate × avg_duration`.

But the maintainer asked for **two** controls at grill round 2:

- Target concurrency (1–50)
- Call rate (calls per second)

Immediately obvious: **these are not independent**. By Little's Law (`L = λW`,
concurrent = rate × average duration), once the duration weights are fixed (REQ-F-041),
adjusting either slider affects both the resulting concurrency and the resulting rate.
Pushing rate up pushes concurrency up; pulling rate down lets the pool drain; adjusting
target concurrency does not change rate directly but caps the pool below what
`rate × avg_duration` would naturally produce.

The maintainer's exact question at round 2: "我不知道你如何控制这一点" about how target
concurrency works alongside call rate, and Q4's "在 console 上通过滑动按钮控制 QPS from
0.1 to 10（或者更小）是可以接受的" established that both are desired.

Three design candidates:

### Option A — Single control (collapse to call rate only)

One slider for call rate. Concurrent calls emerge naturally as `rate × avg_duration`.
Simplest model. But loses the pool ceiling — the reviewer cannot directly say "I want
15 concurrent calls" and see the generator respect that exactly.

### Option B — Two controls, independent (pretend they don't couple)

Both sliders exist. The generator tries to honor both simultaneously without acknowledging
Little's Law. Produces undefined behavior when the two controls pull in opposite
directions — rate=10/sec + target=15 + avg_duration=10s would need 100 concurrent
calls to keep up with the rate, but target caps at 15. Which wins?

### Option C — Two controls, explicitly coupled (chosen)

Both sliders exist. They control **two different dimensions of the same pool**, not the
same quantity:

- **Target concurrency (1–50) = pool ceiling.** Closed-loop control. The tick loop
  fills the pool to `target_concurrency` on every tick. Never exceeded.
- **Call rate (0.1–10 calls/sec) = refill speed throttle.** Open-loop control.
  Even if the pool is below target, no more than `rate` calls per second are launched.
  Rate budget is accumulated per second (500 ms tick → half the budget per tick).

Whichever constraint is more restrictive at any moment is **binding**:

| Condition | What happens | Console shows |
|-----------|-------------|---------------|
| `rate × avg_duration >= target_concurrency` | Concurrency is binding — pool stabilises at `target`, rate throttle never reached | "约束因子: 池子上限" |
| `rate × avg_duration < target_concurrency` | Rate is binding — pool stabilises at `rate × avg_duration` below target | "约束因子: Call Rate 限速" |

## Decision

**Option C.** Two controls with an explicit binding-constraint rule.

The `avg_duration` used in the coupling calculation is a fixed constant derived from
REQ-F-041's duration weights. The generator computes it once at startup:

```python
avg_duration = (
    0.30 * 2.5 +   # D1 fast (2-3s, midpoint 2.5)
    0.50 * 11.5 +  # D2 medium (8-15s, midpoint 11.5)
    0.15 * 25.0 +  # D3 long (20-30s, midpoint 25)
    0.05 * 3.0     # D4 timeout (3s, fixed)
) = 9.5 seconds  # not published, only used internally
```

This is a **design constant** (derived from REQ-F-041's weights, not from measured
runtime data). The binding constraint is computed by the generator on every tick
(simple arithmetic, no measurement required) and exposed in the `/load/status`
response and every `pool_status_update` event.

## Consequences

### What we gain

- **Reviewer agency.** Both controls give the reviewer direct control over "how many"
  (target concurrency) and "how fast" (call rate). A reviewer can say "pull the
  pool up to 20, then watch what happens when we starve it by pulling rate down"
  — an educational demo that shows Little's Law at work, not just numbers.
- **Binding constraint indicator on console (P13).** The console shows which control
  is currently limiting. This is not decoration — it explains why the pool is at its
  current level, which makes the demo comprehensible to someone who does not know
  Little's Law going in.
- **Bursty call pattern simulation.** A reviewer can set a high target concurrency
  (pool ceiling) with a low rate (slow refill) to simulate the scenario where all
  active calls end simultaneously — the rate throttle prevents a "flash flood" of
  new calls that would otherwise spike the loop gap.

### What we accept

- **Two sliders that are not independent.** The maintainer's round-2 question
  ("我不知道你如何控制这一点") is acknowledged and answered, not hidden. The
  coupling is the design feature, not the design problem.
- **An `avg_duration` constant that is "good enough".** We do not measure actual
  average call duration at runtime and feed it back — we use the weight-derived
  constant. If a reviewer sets rate=1/sec and target=15, the pool will stabilise
  around `1 × 9.5 = 9.5` calls, not exactly 10 — but that is fine because P12 never
  publishes numbers (REQ-NF-025, D-P3-3). The demo shows the *interaction*, not the
  exact values.

### What we explicitly do NOT do

- **Do not make `avg_duration` user-adjustable.** Duration weights are fixed at
  D1 30% / D2 50% / D3 15% / D4 5% (REQ-F-041). A duration-adjustment slider would
  add a third dimension to the coupling and complicate the console without
  proportional demo value. The duration weights are a design constant.
- **Do not measure runtime duration and feed it back.** This would create a feedback
  loop that makes the binding constraint calculation non-deterministic. Simple
  weight-derived constant wins over measurement.
