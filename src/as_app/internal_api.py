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

Until then the AS serves the same payloads from a minimal standard-library HTTP server
that runs on its own thread. It is deliberately not a web framework: ``ED2.loop()`` owns
the main thread (ADR-0002), so nothing here may block the sippy event loop.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from as_app.observability.metrics import MetricsRegistry
from as_app.observability.tracing import CallTrace, TraceEvent, TraceRecorder
from as_app.routing.rules import RuleSet, RuleSetStore

__all__ = [
    "INTERNAL_API_ROUTES",
    "InternalApiServer",
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


def traces_payload(recorder: TraceRecorder, limit: int = 20) -> dict[str, Any]:
    """Build the list of the most recent calls for the console.

    Args:
        recorder: The trace recorder of the AS process.
        limit: Maximum number of calls to include.

    Returns:
        The document served on ``GET /api/v1/traces``.
    """
    return {"calls": [trace_payload(trace) for trace in recorder.recent(limit)]}


class InternalApiServer:
    """Minimal internal API server for the health endpoint and the counters.

    M1 needs a live health endpoint and readable counters, but the console itself is M3.
    This server therefore uses the standard library only, runs on its own daemon thread
    and serves the very payloads the FastAPI application will serve in M3. It never
    touches sippy and it never blocks ``ED2.loop()`` (ADR-0002).

    Attributes:
        address: Local address the server binds.
        port: Local TCP port the server binds.
        version: Version reported by the health endpoint.
        rule_set_store: Source of the active rule set, reported as readiness.
        metrics: Counter registry exposed on ``/api/v1/metrics``.
        tracer: Trace recorder exposed on ``/api/v1/traces``.
    """

    def __init__(
        self,
        address: str,
        port: int,
        *,
        version: str,
        rule_set_store: RuleSetStore,
        metrics: MetricsRegistry,
        tracer: TraceRecorder,
    ) -> None:
        """Create the internal API server.

        Args:
            address: Local address to bind.
            port: Local TCP port to bind.
            version: Version reported by the health endpoint.
            rule_set_store: Source of the active rule set.
            metrics: Counter registry.
            tracer: Trace recorder.
        """
        self.address = address
        self.port = port
        self.version = version
        self.rule_set_store = rule_set_store
        self.metrics = metrics
        self.tracer = tracer
        self.started_at = time.monotonic()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def uptime_seconds(self) -> float:
        """Seconds since the server was created."""
        return time.monotonic() - self.started_at

    def start(self) -> None:
        """Bind the port and serve in the background.

        Raises:
            OSError: When the address and port cannot be bound.
        """
        self._httpd = ThreadingHTTPServer((self.address, self.port), self._make_handler())
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="internal-api", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        """Build the request handler class bound to this server instance.

        Returns:
            A ``BaseHTTPRequestHandler`` subclass serving the internal API routes.
        """
        server = self

        class InternalApiHandler(BaseHTTPRequestHandler):
            """Serves the internal API routes from the enclosing server instance."""

            server_version = "as-internal-api/1.0"

            def do_GET(self) -> None:  # noqa: N802 - stdlib naming
                """Answer a ``GET`` request.

                Returns:
                    ``None``; the response is written to the socket.
                """
                payload, status = server._response_for(self.path)
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: Any) -> None:
                """Keep the internal API out of the structured application log.

                Args:
                    fmt: Unused stdlib format string.
                    *args: Unused stdlib format arguments.
                """

        return InternalApiHandler

    def _response_for(self, path: str) -> tuple[dict[str, Any], int]:
        """Build the payload and status code for a request path.

        Args:
            path: Request path, without query string handling.

        Returns:
            The payload and the HTTP status code.
        """
        route = path.split("?", 1)[0]
        if route in ("/healthz", "/health"):
            return (
                health_payload(
                    version=self.version,
                    uptime_seconds=self.uptime_seconds,
                    rule_set_loaded=self.rule_set_store.current is not None,
                ),
                200,
            )
        if route == "/api/v1/metrics":
            return (metrics_payload(self.metrics), 200)
        if route == "/api/v1/traces":
            return (traces_payload(self.tracer), 200)
        return ({"error": "not found", "path": route}, 404)
