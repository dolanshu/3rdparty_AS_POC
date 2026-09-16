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

"""Unit tests for the internal API payload builders used by the console."""

from __future__ import annotations

import pytest

from as_app.internal_api import (
    INTERNAL_API_ROUTES,
    health_payload,
    metrics_payload,
    rules_payload,
    trace_payload,
)
from as_app.observability.logging import LogDirection
from as_app.observability.metrics import CallDisposition, MetricsRegistry
from as_app.observability.tracing import TraceRecorder

pytestmark = pytest.mark.unit


def test_documented_routes_cover_health_metrics_rules_and_traces() -> None:
    """The internal API exposes what the console needs (AGENT.md section 4.4)."""
    joined = " ".join(INTERNAL_API_ROUTES)
    for fragment in (
        "/healthz",
        "/api/v1/metrics",
        "/api/v1/rules",
        "/api/v1/traces",
        "/ws/events",
    ):
        assert fragment in joined


def test_health_payload_reports_rule_set_state() -> None:
    """Health degrades when no rule set is active."""
    assert (
        health_payload(version="0.1.0", uptime_seconds=1.0, rule_set_loaded=True)["status"] == "ok"
    )
    assert (
        health_payload(version="0.1.0", uptime_seconds=1.0, rule_set_loaded=False)["status"]
        == "degraded"
    )


def test_metrics_payload_exposes_the_counters() -> None:
    """The statistics dashboard is fed from the counter registry."""
    registry = MetricsRegistry()
    registry.record_call_started()
    registry.record_call_disposition(CallDisposition.NO_MATCH)
    payload = metrics_payload(registry)
    assert payload["calls_total"] == 1
    assert payload["calls_by_disposition"]["no_match"] == 1


def test_rules_payload_is_serialisable_and_read_only(rule_set) -> None:
    """The console receives the whole rule set as JSON-serialisable data."""
    payload = rules_payload(rule_set)
    assert payload["name"] == "sample-office-routing"
    assert len(payload["rules"]) >= 10
    assert len(payload["next_hops"]) >= 2
    assert all(isinstance(rule["rule_id"], str) for rule in payload["rules"])


def test_trace_payload_is_keyed_by_call_id() -> None:
    """A trace carries every event of one call, in order."""
    recorder = TraceRecorder()
    recorder.record("call-1", LogDirection.INBOUND, "INVITE", "inbound invite")
    recorder.record(
        "call-1", LogDirection.OUTBOUND, "INVITE", "outbound invite", rule_id="R-EMG-01"
    )
    payload = trace_payload(recorder.trace_for("call-1"))
    assert payload["call_id"] == "call-1"
    assert [event["method"] for event in payload["events"]] == ["INVITE", "INVITE"]
    assert payload["events"][1]["rule_id"] == "R-EMG-01"
