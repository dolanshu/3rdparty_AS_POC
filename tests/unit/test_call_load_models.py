"""Tests for P12 Call Load generator data structures.

Covers: CallModel (weighted-random call type selection), DurationModel
(fixed-weight duration classes), PoolConfig (validation), CallInstance
(dataclass fields). These are pure-Python with no network or sippy.
"""
from __future__ import annotations

import pytest

from tools.call_load_generator import CallModel, CallInstance, DurationModel, PoolConfig


# ---------------------------------------------------------------------------
# CallModel
# ---------------------------------------------------------------------------


def test_call_model_pick_from_enabled_types():
    """CallModel.pick() only returns types in the enabled set."""
    enabled = {"T1", "T2", "F1", "F2"}
    for _ in range(1000):
        result = CallModel.pick(enabled)
        assert result in enabled, f"Got disabled type: {result}"


def test_call_model_pick_covers_all_types_when_all_enabled():
    """CallModel.pick() can return every one of the 10 types."""
    all_types = {f"T{i}" for i in range(1, 7)} | {f"F{i}" for i in range(1, 5)}
    seen: set[str] = set()
    for _ in range(5000):
        seen.add(CallModel.pick(all_types))
    missing = all_types - seen
    assert not missing, f"CallModel failed to ever pick: {missing}"


def test_call_model_rejects_empty_enabled():
    with pytest.raises(ValueError, match="must not be empty"):
        CallModel.pick(set())


def test_call_model_rejects_unknown_types():
    with pytest.raises(ValueError, match="Unknown call types"):
        CallModel.pick({"T1", "INVALID"})


def test_call_model_all_types_constant():
    """ALL_TYPES is exactly the 10 expected keys."""
    expected = {f"T{i}" for i in range(1, 7)} | {f"F{i}" for i in range(1, 5)}
    assert CallModel.ALL_TYPES == expected


# ---------------------------------------------------------------------------
# DurationModel
# ---------------------------------------------------------------------------


def test_duration_model_weights_sum_to_one():
    total = sum(DurationModel.WEIGHTS.values())
    assert abs(total - 1.0) < 0.001


def test_duration_model_pick_returns_valid_class():
    valid = set(DurationModel.WEIGHTS.keys())
    for _ in range(1000):
        assert DurationModel.pick() in valid


def test_duration_model_midpoints_cover_all_classes():
    """Every weight key has a midpoint entry."""
    assert set(DurationModel.MIDPOINTS.keys()) == set(DurationModel.WEIGHTS.keys())


def test_duration_model_avg_duration_constant():
    """AVG_DURATION_SECONDS matches the documented LLD constant."""
    expected = 0.30 * 2.5 + 0.50 * 11.5 + 0.15 * 25.0 + 0.05 * 3.0
    assert abs(DurationModel.AVG_DURATION_SECONDS - expected) < 0.001


# ---------------------------------------------------------------------------
# PoolConfig
# ---------------------------------------------------------------------------


def test_pool_config_accepts_valid_values():
    cfg = PoolConfig(
        target_concurrency=10,
        call_rate=3.0,
        enabled_call_types=frozenset({"T1", "T2", "F1", "F2"}),
    )
    assert cfg.target_concurrency == 10
    assert cfg.call_rate == 3.0


def test_pool_config_rejects_concurrency_too_low():
    with pytest.raises(ValueError, match="target_concurrency"):
        PoolConfig(0, call_rate=3.0, enabled_call_types=frozenset({"T1"}))


def test_pool_config_rejects_concurrency_too_high():
    with pytest.raises(ValueError, match="target_concurrency"):
        PoolConfig(51, call_rate=3.0, enabled_call_types=frozenset({"T1"}))


def test_pool_config_rejects_rate_too_low():
    with pytest.raises(ValueError, match="call_rate"):
        PoolConfig(10, call_rate=0.05, enabled_call_types=frozenset({"T1"}))


def test_pool_config_rejects_rate_too_high():
    with pytest.raises(ValueError, match="call_rate"):
        PoolConfig(10, call_rate=15.0, enabled_call_types=frozenset({"T1"}))


def test_pool_config_rejects_empty_enabled():
    with pytest.raises(ValueError, match="enabled_call_types"):
        PoolConfig(10, call_rate=3.0, enabled_call_types=frozenset())


def test_pool_config_rejects_unknown_types():
    with pytest.raises(ValueError, match="Unknown call types"):
        PoolConfig(10, call_rate=3.0, enabled_call_types=frozenset({"T1", "INVALID"}))


# ---------------------------------------------------------------------------
# CallInstance
# ---------------------------------------------------------------------------


def test_call_instance_defaults():
    inst = CallInstance(
        call_id="gen-abc123",
        call_type="T1",
        duration_class="D2",
        state="invited",
        far_end_behavior="answer_and_bye",
        started_at=100.0,
    )
    assert inst.call_id == "gen-abc123"
    assert inst.ended_at is None


def test_call_instance_explicit_ended_at():
    inst = CallInstance(
        call_id="gen-abc123",
        call_type="F2",
        duration_class="D4",
        state="ended",
        far_end_behavior="timeout_no_answer",
        started_at=100.0,
        ended_at=103.0,
    )
    assert inst.ended_at == 103.0
