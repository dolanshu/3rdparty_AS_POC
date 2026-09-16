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

"""Unit tests for counters, per-Call-ID tracing and structured logging."""

from __future__ import annotations

import io
import json
import logging

import pytest

from as_app.observability.logging import LogDirection, configure_logging, get_logger, log_event
from as_app.observability.metrics import CallDisposition, MetricsRegistry, PeerStatus
from as_app.observability.tracing import TraceRecorder

pytestmark = pytest.mark.unit


def test_counters_are_counted_per_disposition_code_and_rule() -> None:
    """Counters record dispositions, error codes, rule hits and peer state."""
    registry = MetricsRegistry()
    registry.record_call_started()
    registry.record_call_disposition(CallDisposition.COMPLETED)
    registry.record_error("AS-ROUTE-001")
    registry.record_rule_hit("R-EMG-01")
    registry.set_peer_status("s-sbc-primary", PeerStatus.REACHABLE)

    snapshot = registry.snapshot()
    assert snapshot.calls_total == 1
    assert snapshot.calls_by_disposition == {"completed": 1}
    assert snapshot.errors_by_code == {"AS-ROUTE-001": 1}
    assert snapshot.rule_hits == {"R-EMG-01": 1}
    assert snapshot.peer_status == {"s-sbc-primary": "reachable"}


def test_trace_is_keyed_by_call_id_and_keeps_order() -> None:
    """Events of one Call-ID stay in order and separate from other calls."""
    recorder = TraceRecorder()
    recorder.record(
        "call-a", LogDirection.INBOUND, "INVITE", "inbound invite", peer="127.0.0.1:15060"
    )
    recorder.record("call-b", LogDirection.OUTBOUND, "INVITE", "outbound invite")
    recorder.record("call-a", LogDirection.INTERNAL, "decision", "route", rule_id="R-EMG-01")

    trace = recorder.trace_for("call-a")
    assert [event.method for event in trace.events] == ["INVITE", "decision"]
    # most recently updated first: call-a was touched again after call-b
    assert recorder.known_call_ids() == ["call-a", "call-b"]
    assert recorder.recent(limit=1)[0].call_id == "call-a"


def test_trace_recorder_is_bounded() -> None:
    """The recorder keeps only the most recent calls."""
    recorder = TraceRecorder(max_calls=2)
    for index in range(4):
        recorder.record(f"call-{index}", LogDirection.INTERNAL, "decision", "route")
    assert recorder.known_call_ids() == ["call-3", "call-2"]


def test_structured_log_line_carries_the_mandatory_fields() -> None:
    """Every log line has timestamp, level, module, call_id, direction, peer, event."""
    stream = io.StringIO()
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        configure_logging("INFO", structured=True)
        for handler in list(root.handlers):
            handler.stream = stream  # type: ignore[attr-defined]
        log_event(
            get_logger("as_app.test"),
            logging.INFO,
            "inbound invite received",
            call_id="call-1",
            direction=LogDirection.INBOUND,
            peer="127.0.0.1:15060",
            method="INVITE",
        )
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)

    line = json.loads(stream.getvalue().strip())
    assert line["call_id"] == "call-1"
    assert line["direction"] == "in"
    assert line["peer"] == "127.0.0.1:15060"
    assert line["event"] == "inbound invite received"
    assert line["method"] == "INVITE"
    assert line["level"] == "info"
    assert "timestamp" in line and "module" in line
