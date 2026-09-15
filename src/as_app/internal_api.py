# Copyright 2026 the 3rd-party AS POC authors.
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

"""Internal REST and WebSocket surface used by the console.

The AS and the console are separate processes: sippy's ``ED2.loop()`` blocks, so it can
never share a thread or an asyncio loop with a web server (ADR-0002). The console talks
to the AS only through this API, never by importing AS modules.

M0 defines the payload shapes; the FastAPI application behind them is built in M3.
"""

from __future__ import annotations

from typing import Any

from as_app.observability.metrics import MetricsRegistry
from as_app.observability.tracing import CallTrace, TraceEvent
from as_app.routing.rules import RuleSet

__all__ = [
    "INTERNAL_API_ROUTES",
    "health_payload",
    "metrics_payload",
    "rules_payload",
    "trace_payload",
]

#: Endpoints the console may use. Address and port come from ``INTERNAL_API_*``
#: (``AGENT.md`` section 8).
INTERNAL_API_ROUTES: dict[str, str] = {
    "GET /healthz": "liveness and readiness of the AS process",
    "GET /api/v1/metrics": "counters, dispositions, rule hits, peer status",
    "GET /api/v1/rules": "active rule set, read-only (rules are edited as data files)",
    "GET /api/v1/traces": "most recent calls with their trace events",
    "GET /api/v1/traces/{call_id}": "one call, Call-ID keyed",
    "WS /ws/events": "live event feed for the console",
}


def health_payload(*, version: str, uptime_seconds: float, rule_set_loaded: bool) -> dict[str, Any]:
    """Build the health endpoint payload.

    Args:
        version: Version of the AS.
        uptime_seconds: Seconds since process start.
        rule_set_loaded: Whether a rule set is active.

    Returns:
        The health document served on ``GET /healthz``.
    """
    return {
        "status": "ok" if rule_set_loaded else "degraded",
        "version": version,
        "uptime_seconds": round(uptime_seconds, 3),
        "rule_set_loaded": rule_set_loaded,
    }


def metrics_payload(registry: MetricsRegistry) -> dict[str, Any]:
    """Build the statistics payload from the counter registry.

    Args:
        registry: The metrics registry of the AS process.

    Returns:
        The document served on ``GET /api/v1/metrics``.
    """
    snapshot = registry.snapshot()
    return {
        "calls_total": snapshot.calls_total,
        "calls_by_disposition": snapshot.calls_by_disposition,
        "errors_by_code": snapshot.errors_by_code,
        "rule_hits": snapshot.rule_hits,
        "peer_status": snapshot.peer_status,
    }


def rules_payload(rule_set: RuleSet) -> dict[str, Any]:
    """Build the read-only rules payload for the console.

    Args:
        rule_set: The active rule set.

    Returns:
        The document served on ``GET /api/v1/rules``.
    """
    document = rule_set.document
    return {
        "source": str(rule_set.source),
        "name": document.name,
        "description": document.description,
        "version": document.version,
        "next_hops": [hop.model_dump() for hop in document.next_hops],
        # All rules are reported, including disabled ones: the console shows the file as
        # it is on disk, while the engine only evaluates enabled rules.
        "rules": [rule.model_dump(mode="json") for rule in document.rules],
    }


def trace_payload(trace: CallTrace) -> dict[str, Any]:
    """Build the Call-ID keyed trace payload.

    Args:
        trace: The trace of one call.

    Returns:
        The document served on ``GET /api/v1/traces/{call_id}``.
    """
    return {
        "call_id": trace.call_id,
        "events": [_event_payload(event) for event in trace.events],
    }


def _event_payload(event: TraceEvent) -> dict[str, Any]:
    """Serialise one trace event.

    Args:
        event: The trace event.

    Returns:
        A JSON-serialisable representation of the event.
    """
    return {
        "timestamp": event.timestamp.isoformat(),
        "call_id": event.call_id,
        "direction": event.direction,
        "method": event.method,
        "peer": event.peer,
        "summary": event.summary,
        "rule_id": event.rule_id,
        "attributes": event.attributes,
    }
