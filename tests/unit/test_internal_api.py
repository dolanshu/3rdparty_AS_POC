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
        "/messages",
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


# ======================================================================
# SimplePublisher fanout tests (P12 REQ-F-042)
# ======================================================================


class _FakeWebSocket:
    """Minimal WebSocket mock that records sent messages."""

    def __init__(self, name: str = "ws1", *, fail_next_send: bool = False) -> None:
        self.name = name
        self.messages: list[str] = []
        self.accepted = False
        self.fail_next_send = fail_next_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, msg: str) -> None:
        if self.fail_next_send:
            self.fail_next_send = False  # one-shot
            raise ConnectionError("boom")
        self.messages.append(msg)

    async def receive_text(self) -> str:  # pragma: no cover - not exercised
        raise Exception("test loop not reading")


@pytest.mark.asyncio
async def test_simple_publisher_connect_accepts_and_tracks() -> None:
    from as_app.internal_api import SimplePublisher

    pub = SimplePublisher()
    ws = _FakeWebSocket()
    await pub.connect(ws)
    assert ws.accepted is True
    assert len(pub._connections) == 1


@pytest.mark.asyncio
async def test_simple_publisher_broadcast_sends_to_all() -> None:
    from as_app.internal_api import SimplePublisher

    pub = SimplePublisher()
    wsa = _FakeWebSocket("A")
    wsb = _FakeWebSocket("B")
    await pub.connect(wsa)
    await pub.connect(wsb)
    await pub.broadcast("hello")
    assert wsa.messages == ["hello"]
    assert wsb.messages == ["hello"]


@pytest.mark.asyncio
async def test_simple_publisher_dead_connection_is_pruned() -> None:
    from as_app.internal_api import SimplePublisher

    pub = SimplePublisher()
    dead = _FakeWebSocket("dead", fail_next_send=True)
    alive = _FakeWebSocket("alive")
    await pub.connect(dead)
    await pub.connect(alive)
    await pub.broadcast("first")  # dead fails here → pruned
    assert alive.messages == ["first"]
    assert dead not in pub._connections


@pytest.mark.asyncio
async def test_simple_publisher_disconnect_removes() -> None:
    from as_app.internal_api import SimplePublisher

    pub = SimplePublisher()
    ws = _FakeWebSocket()
    await pub.connect(ws)
    pub.disconnect(ws)
    assert len(pub._connections) == 0


@pytest.mark.asyncio
async def test_simple_publisher_empty_connections_is_noop() -> None:
    from as_app.internal_api import SimplePublisher

    pub = SimplePublisher()
    await pub.broadcast("nothing-to-send")  # must not raise


# ======================================================================
# InternalApiServer P12 eager-build tests
# ======================================================================


def test_internal_api_server_eager_builds_app_before_start(rules_file) -> None:
    """P12: server.app must exist right after __init__, before start()."""
    from as_app.internal_api import InternalApiServer
    from as_app.observability.metrics import MetricsRegistry
    from as_app.observability.tracing import TraceRecorder
    from as_app.routing.rules import RuleSetStore

    server = InternalApiServer(
        "127.0.0.1",
        0,
        version="0.1.0",
        rule_set_store=RuleSetStore(rules_file),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
    )
    # app exists eagerly and carries the broadcast fanout hook
    assert server.app is not None
    assert hasattr(server.app.state, "broadcast")
    assert hasattr(server.app.state, "publisher")
    assert not hasattr(server.app.state, "_loop")  # only set after start() daemon thread


def test_internal_api_server_app_has_p12_websocket_route(rules_file) -> None:
    """P12: /ws/p12/events WebSocket is mounted on the app."""
    from as_app.internal_api import InternalApiServer
    from as_app.observability.metrics import MetricsRegistry
    from as_app.observability.tracing import TraceRecorder
    from as_app.routing.rules import RuleSetStore

    server = InternalApiServer(
        "127.0.0.1",
        0,
        version="0.1.0",
        rule_set_store=RuleSetStore(rules_file),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
    )
    routes = [getattr(r, "path", "") for r in server.app.routes]
    assert "/ws/p12/events" in routes
