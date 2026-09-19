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

"""Internal REST and WebSocket surface used by the console.

The AS and the console are separate processes: sippy's ``ED2.loop()`` blocks, so it can
never share a thread or an asyncio loop with a web server (ADR-0002). The console talks
to the AS only through this API, never by importing AS modules.

The AS serves the API from a daemon thread via uvicorn; it only reads snapshots (counters
and traces are lock-guarded), so it never blocks the sippy event loop (ADR-0002,
``AGENT.md`` section 6). CORS is open because the console runs on a different port and
the API is a loopback-only demo surface (ADR-0002, gaps accepted).

Endpoints (ADR-0002)::

    GET /healthz                   — liveness and readiness
    GET /api/v1/metrics            — counters, dispositions, rule hits, peer status
    GET /api/v1/rules              — active rule set, read-only
    GET /api/v1/traces             — most recent calls with their trace events
    GET /api/v1/traces/{call_id}   — one call, Call-ID keyed
    WS  /ws/events                 — live event feed for the console
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Final

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from as_app.observability.metrics import MetricsRegistry
from as_app.observability.tracing import CallTrace, TraceEvent, TraceRecorder
from as_app.routing.rules import RuleSet, RuleSetStore

__all__ = [
    "INSTANCE_NAME",
    "INTERNAL_API_ROUTES",
    "InternalApiServer",
    "create_internal_api_app",
    "health_payload",
    "metrics_payload",
    "rules_payload",
    "trace_payload",
    "traces_payload",
]

#: Stable machine identity of this AS instance, reported on ``GET /healthz``. Both AS
#: processes share one console page, so the page has to be able to say which of them it is
#: displaying (P8, ADR-0007); the identity is what it renders — never the port, which is
#: configuration.
INSTANCE_NAME: Final[str] = "number-translation"

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

#: Polling interval, in seconds, of the WebSocket event feed. The TraceRecorder is a
#: passive store (not a pub/sub), so the feed polls it for new calls and pushes the
#: delta. This is a POC simplification — see ``docs/production-gaps.md``.
_WS_POLL_SECONDS = 1.0

#: Maximum number of traces the WebSocket feed sends in one batch.
_WS_MAX_TRACES = 50


def health_payload(
    *,
    version: str,
    uptime_seconds: float,
    rule_set_loaded: bool,
    instance: str = INSTANCE_NAME,
) -> dict[str, Any]:
    """Build the health endpoint payload.

    Args:
        version: Version of the AS.
        uptime_seconds: Seconds since process start.
        rule_set_loaded: Whether a rule set is active.
        instance: Machine identity of the instance answering; defaults to this module's.

    Returns:
        The health document served on ``GET /healthz``.
    """
    return {
        "status": "ok" if rule_set_loaded else "degraded",
        "instance": instance,
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
        # Application-specific counters (for example the anti-fraud screening verdicts).
        # Empty for the number-translation AS; additive, so the console contract holds.
        "counters": snapshot.counters,
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


def create_internal_api_app(
    *,
    version: str,
    rule_set_store: RuleSetStore,
    metrics: MetricsRegistry,
    tracer: TraceRecorder,
    started_at: float,
) -> FastAPI:
    """Create the FastAPI application for the internal API.

    The app factory is the seam between the pure payload builders and the AS process
    state. It closes over the registries so every route handler is a thin read of a
    lock-guarded snapshot (ADR-0002).

    Args:
        version: Version reported by the health endpoint.
        rule_set_store: Source of the active rule set, reported as readiness.
        metrics: Counter registry exposed on ``/api/v1/metrics``.
        tracer: Trace recorder exposed on ``/api/v1/traces``.
        started_at: ``time.monotonic()`` value at server creation, for uptime.

    Returns:
        A FastAPI application with the internal API routes.
    """
    app = FastAPI(title="3rd-party AS internal API", version=version)

    # The console is a separate process on a different port; the API is loopback-only
    # (ADR-0002, gaps accepted). Open CORS lets the browser fetch directly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        """Liveness and readiness of the AS process.

        Returns:
            The health document with status, version, uptime and rule-set state.
        """
        return health_payload(
            version=version,
            uptime_seconds=time.monotonic() - started_at,
            rule_set_loaded=rule_set_store.current is not None,
        )

    @app.get("/api/v1/metrics")
    def get_metrics() -> dict[str, Any]:
        """Counters, dispositions, rule hits and peer status.

        Returns:
            The metrics snapshot document.
        """
        return metrics_payload(metrics)

    @app.get("/api/v1/rules")
    def get_rules() -> dict[str, Any]:
        """The active rule set, read-only.

        Returns:
            The rules document, or a 503 when no rule set is loaded.
        """
        rule_set = rule_set_store.current
        if rule_set is None:
            return JSONResponse({"error": "no rule set loaded"}, status_code=503)
        return rules_payload(rule_set)

    @app.get("/api/v1/traces")
    def get_traces() -> dict[str, Any]:
        """Most recent calls with their trace events.

        Returns:
            The traces list document.
        """
        return traces_payload(tracer)

    @app.get("/api/v1/traces/{call_id}")
    def get_trace(call_id: str) -> dict[str, Any]:
        """One call, Call-ID keyed.

        Args:
            call_id: SIP Call-ID of the call.

        Returns:
            The trace document for the call (empty events when unknown).
        """
        return trace_payload(tracer.trace_for(call_id))

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket) -> None:
        """Live event feed for the console.

        Polls the trace recorder for new calls and pushes them as JSON batches. The
        recorder is a passive store, so the feed is pull-based at a fixed interval — a
        POC simplification documented in ``docs/production-gaps.md``.

        Args:
            websocket: The WebSocket connection from the console.
        """
        await websocket.accept()
        seen_call_ids: set[str] = set(tracer.known_call_ids())
        try:
            while True:
                await asyncio.sleep(_WS_POLL_SECONDS)
                current_ids = set(tracer.known_call_ids())
                new_ids = current_ids - seen_call_ids
                if new_ids:
                    recent = tracer.recent(limit=_WS_MAX_TRACES)
                    payload = {
                        "type": "traces",
                        "traces": [trace_payload(t) for t in recent if t.call_id in new_ids],
                    }
                    await websocket.send_json(payload)
                    seen_call_ids = current_ids
        except WebSocketDisconnect:
            pass

    return app


class InternalApiServer:
    """FastAPI/uvicorn internal API server running on a daemon thread.

    The AS process serves its internal API from this server. It runs on a daemon thread
    with its own asyncio event loop (uvicorn installs no signal handlers on non-main
    threads), so it never blocks the sippy event loop (ADR-0002). Every route handler
    only reads lock-guarded snapshots.

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
        self._server: Any = None
        self._thread: threading.Thread | None = None

    @property
    def uptime_seconds(self) -> float:
        """Seconds since the server was created."""
        return time.monotonic() - self.started_at

    def start(self) -> None:
        """Bind the port and serve in the background on a daemon thread.

        Raises:
            OSError: When the address and port cannot be bound.
        """
        import uvicorn  # imported lazily: only the AS process runs the server

        app = create_internal_api_app(
            version=self.version,
            rule_set_store=self.rule_set_store,
            metrics=self.metrics,
            tracer=self.tracer,
            started_at=self.started_at,
        )
        config = uvicorn.Config(
            app,
            host=self.address,
            port=self.port,
            log_level="error",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="internal-api", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._server = None
