# Copyright 2026 Dolan Shu <dolan.d.shu@gmail.com>.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the process-level cross-call state (D9).

The call-rate window and the reputation ledger are the only state that survives a call, so
these tests pin down the three properties the design depends on:

- the window counts what fell inside it and forgets what did not;
- reputation decays **towards the default** with a half-life, so a bad burst fades;
- both structures are bounded, because the POC keeps them in memory.

Every test injects a clock, so time is advanced by hand and nothing waits (REQ-NF-011). The
store is also the only object allowed to read a clock, which the last test asserts directly.

Covers ACC-P8-004 (REQ-F-022, REQ-NF-011, REQ-NF-012).
"""

from __future__ import annotations

import time

import pytest

from anti_fraud_as.caller_state import CallerSignals, CallerStateStore, WindowPolicy

pytestmark = pytest.mark.unit

#: Parameters most cases use: a one-minute window of three calls, 100 points that halve
#: every five minutes, 40 points lost per rejected call.
POLICY = WindowPolicy(
    window_seconds=60.0,
    max_calls=3,
    half_life_seconds=300.0,
    default_score=100.0,
    reject_penalty=40.0,
    max_tracked_callers=100,
)

CALLER = "+8613400000001"


class FakeClock:
    """A monotonic clock a test advances by hand.

    Attributes:
        now: The instant the clock currently reads.
    """

    def __init__(self, now: float = 1000.0) -> None:
        """Create the clock at a fixed instant.

        Args:
            now: The instant to start at.
        """
        self.now = now
        self.reads = 0

    def __call__(self) -> float:
        """Return the current instant.

        Returns:
            The instant the clock reads.
        """
        self.reads += 1
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        Args:
            seconds: How far to move it.
        """
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    """Return a fresh hand-driven clock.

    Returns:
        A :class:`FakeClock` at a fixed starting instant.
    """
    return FakeClock()


@pytest.fixture
def store(clock: FakeClock) -> CallerStateStore:
    """Return a store bound to the test clock.

    Args:
        clock: The clock the store reads.

    Returns:
        A :class:`CallerStateStore` with :data:`POLICY`.
    """
    return CallerStateStore(POLICY, clock=clock)


def test_observe_records_the_call_and_returns_plain_signals(store: CallerStateStore) -> None:
    """The controller sees plain values, never the store's internals."""
    signals = store.observe(CALLER)

    assert isinstance(signals, CallerSignals)
    assert signals.calling_number == CALLER
    assert signals.calls_in_window == 1
    assert signals.effective_reputation == POLICY.default_score


def test_repeated_calls_accumulate_up_to_the_cap(store: CallerStateStore) -> None:
    """Each observation adds one call, and the count saturates at the cap.

    The deque is bounded to ``max_calls + 1`` entries, so once a caller is past the
    threshold the count stops growing: the store never needs to know *how far* past it is,
    which is what keeps the in-memory state bounded (REQ-NF-012).
    """
    counts = [store.observe(CALLER).calls_in_window for _ in range(6)]

    assert counts == [1, 2, 3, 4, 4, 4]
    assert counts[-1] > POLICY.max_calls


def test_calls_older_than_the_window_are_forgotten(
    store: CallerStateStore, clock: FakeClock
) -> None:
    """A burst that has aged out no longer counts against the caller."""
    for _ in range(4):
        store.observe(CALLER)

    clock.advance(POLICY.window_seconds + 1.0)

    assert store.observe(CALLER).calls_in_window == 1


def test_the_window_boundary_is_exclusive(store: CallerStateStore, clock: FakeClock) -> None:
    """A call exactly one window old has left the window, not just reached its edge."""
    store.observe(CALLER)

    clock.advance(POLICY.window_seconds)

    assert store.observe(CALLER).calls_in_window == 1


def test_calls_inside_the_window_still_count(store: CallerStateStore, clock: FakeClock) -> None:
    """The opposite side of the same boundary: still inside means still counted."""
    store.observe(CALLER)

    clock.advance(POLICY.window_seconds - 1.0)

    assert store.observe(CALLER).calls_in_window == 2


def test_a_callers_window_is_bounded(store: CallerStateStore) -> None:
    """A caller's deque keeps at most ``max_calls + 1`` entries, however loud it is."""
    for _ in range(50):
        store.observe(CALLER)

    # The bound is asserted through the count the store reports, not through the deque.
    assert store.observe(CALLER).calls_in_window == POLICY.max_calls + 1


def test_the_store_is_bounded_across_callers(store: CallerStateStore) -> None:
    """Tracked callers are capped, oldest first, so memory cannot grow without limit."""
    bounded = CallerStateStore(
        WindowPolicy(
            window_seconds=POLICY.window_seconds,
            max_calls=POLICY.max_calls,
            half_life_seconds=POLICY.half_life_seconds,
            default_score=POLICY.default_score,
            reject_penalty=POLICY.reject_penalty,
            max_tracked_callers=2,
        ),
        clock=lambda: 1000.0,
    )
    for caller in ("+8613400000001", "+8613400000002", "+8613400000003"):
        bounded.observe(caller)

    # The cap is exactly two and the caller dropped is the oldest: the second caller is
    # still tracked (two calls) while the first is seen as new (one call).
    assert bounded.observe("+8613400000002").calls_in_window == 2
    assert bounded.observe("+8613400000001").calls_in_window == 1


def test_an_unknown_caller_starts_at_the_default_score(store: CallerStateStore) -> None:
    """Nobody is born with a bad reputation."""
    assert store.observe("+8613400009999").effective_reputation == POLICY.default_score


def test_penalise_subtracts_the_configured_penalty(store: CallerStateStore) -> None:
    """One rejected call costs exactly ``reject_penalty`` points."""
    store.observe(CALLER)

    assert store.penalise(CALLER) == POLICY.default_score - POLICY.reject_penalty


def test_reputation_decays_halfway_back_after_one_half_life(
    store: CallerStateStore, clock: FakeClock
) -> None:
    """A deviation from the default halves in one half-life, so a burst fades."""
    store.observe(CALLER)
    store.penalise(CALLER)

    clock.advance(POLICY.half_life_seconds)

    assert store.observe(CALLER).effective_reputation == pytest.approx(80.0)


def test_reputation_decays_three_quarters_of_the_way_after_two_half_lives(
    store: CallerStateStore, clock: FakeClock
) -> None:
    """The second half-life removes half of what was left, not another 40 points."""
    store.observe(CALLER)
    store.penalise(CALLER)

    clock.advance(POLICY.half_life_seconds * 2)

    assert store.observe(CALLER).effective_reputation == pytest.approx(90.0)


def test_decay_is_monotonic_towards_the_default(store: CallerStateStore, clock: FakeClock) -> None:
    """Every step of the decay moves the caller closer to the default, never past it."""
    store.observe(CALLER)
    store.penalise(CALLER)

    scores = []
    for _ in range(8):
        clock.advance(POLICY.half_life_seconds)
        scores.append(store.observe(CALLER).effective_reputation)

    assert scores == sorted(scores)
    assert all(score <= POLICY.default_score for score in scores)
    # Eight half-lives leave 40 * 2**-8 ≈ 0.16 points of the deviation.
    assert scores[-1] == pytest.approx(POLICY.default_score, abs=1.0)


def test_a_second_penalty_applies_to_the_decayed_score(
    store: CallerStateStore, clock: FakeClock
) -> None:
    """Penalties compound on what is left, so repeated abuse keeps a caller down."""
    store.observe(CALLER)
    store.penalise(CALLER)
    clock.advance(POLICY.half_life_seconds)

    second = store.penalise(CALLER)

    # 60 decayed back to 80, minus the 40-point penalty.
    assert second == pytest.approx(40.0)


def test_reconfigure_changes_the_thresholds_but_keeps_the_history(
    store: CallerStateStore, clock: FakeClock
) -> None:
    """A reload re-reads the parameters; the callers keep the calls they made.

    This is what makes an operator edit take effect without a restart: the recording stays,
    the window it is measured against changes. The reloaded parameters are **genuinely
    different** from :data:`POLICY`, so the assertions below fail if ``reconfigure`` is
    removed or made a no-op: the store would keep answering with the old window, cap and
    default score.
    """
    for _ in range(4):
        store.observe(CALLER)
    assert store.observe(CALLER).calls_in_window == POLICY.max_calls + 1
    assert store.observe("+8613400009999").effective_reputation == POLICY.default_score

    reloaded = WindowPolicy(
        window_seconds=POLICY.window_seconds * 2,
        max_calls=1,
        half_life_seconds=POLICY.half_life_seconds / 2,
        default_score=50.0,
        reject_penalty=5.0,
        max_tracked_callers=7,
    )
    store.reconfigure(reloaded)

    assert store.policy == reloaded
    # The history survived: the calls the caller already made are re-evaluated against the
    # new (smaller) cap, so it is still counted as one over it.
    signals = store.observe(CALLER)
    assert signals.calls_in_window == reloaded.max_calls + 1
    assert signals.calls_in_window > reloaded.max_calls
    # The new parameters are the ones now in force for the reputation too.
    assert store.observe("+8613400009999").effective_reputation == reloaded.default_score


def test_the_store_reads_only_the_injected_clock(
    clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No code path in the store falls back to the wall clock (REQ-NF-011).

    With the real clock replaced by one that raises, the store still works — which is only
    true because every instant it uses comes from the injected callable.
    """
    store = CallerStateStore(POLICY, clock=clock)

    def boom() -> float:
        """Fail if the store reaches for the real clock."""
        raise AssertionError("the store read the wall clock")

    monkeypatch.setattr(time, "monotonic", boom)
    monkeypatch.setattr(time, "time", boom)

    store.observe(CALLER)
    store.penalise(CALLER)

    assert clock.reads >= 2
