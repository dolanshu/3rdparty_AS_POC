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

"""Internal REST and WebSocket surface of the anti-fraud AS.

Its own process, its own API, its own port (ADR-0002, ADR-0007 decision 9). The route set
mirrors the number-translation AS's — ``/healthz``, ``/api/v1/metrics``, ``/api/v1/traces``
and ``WS /ws/events`` — so the existing console can be pointed at either instance, and adds
``GET /api/v1/screening`` for the block/allow lists and the window/reputation parameters.

The app factory and the server are **duplicated on purpose** from ``as_app.internal_api``:
that one is bound to a ``RuleSetStore`` and to ``/api/v1/rules``, so reusing it would mean
parameterising it into the very framework P8 must not build. The duplication is friction for
P10 and is registered as such.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Final

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from anti_fraud_as.screening_data import ListMatch, ScreeningDataStore
from as_app.observability.metrics import MetricsRegistry
from as_app.observability.tracing import CallTrace, TraceEvent, TraceRecorder

__all__ = [
    "INSTANCE_NAME",
    "INTERNAL_API_ROUTES",
    "InternalApiServer",
    "create_internal_api_app",
    "health_payload",
    "metrics_payload",
    "screening_payload",
    "trace_payload",
    "traces_payload",
]

#: Stable machine identity of this AS instance, reported on ``GET /healthz``. Both AS
#: processes are rendered by one console page, so the page has to be able to say which of
#: them it is displaying (ADR-0007); the identity is what it renders — never the port, which
#: is configuration.
INSTANCE_NAME: Final[str] = "anti-fraud"

#: Endpoints the console may use. Address and port come from ``FRAUD_INTERNAL_API_*``.
INTERNAL_API_ROUTES: dict[str, str] = {
    "GET /healthz": "liveness and readiness of the anti-fraud AS process",
    "GET /api/v1/metrics": "counters, verdicts, error codes and peer status",
    "GET /api/v1/screening": "block/allow lists and window/reputation parameters (read-only)",
    "GET /api/v1/traces": "most recent calls with their trace events",
    "GET /api/v1/traces/{call_id}": "one call, Call-ID keyed",
    "WS /ws/events": "live event feed for the console",
}

#: Polling interval, in seconds, of the WebSocket event feed. The recorder is a passive
#: store, not a pub/sub, so the feed polls it — the same POC simplification as the first AS
#: (``docs/production-gaps.md``).
_WS_POLL_SECONDS = 1.0

#: Maximum number of traces the WebSocket feed sends in one batch.
_WS_MAX_TRACES = 50


def health_payload(
    *,
    version: str,
    uptime_seconds: float,
    screening_data_loaded: bool,
    instance: str = INSTANCE_NAME,
) -> dict[str, Any]:
    """Build the health endpoint payload.

    Three readiness keys are reported, and the reasons differ:

    * ``instance`` — the machine identity of this process, so the console can say
      unambiguously which AS it is displaying.
    * ``screening_data_loaded`` — the **honest** readiness key of this instance: the
      anti-fraud AS is ready when its screening data is active.
    * ``rule_set_loaded`` — a **compatibility key only**. The anti-fraud AS has no rule set;
      it is reported with the screening-data state so the one shared console page renders
      both instances without special-casing which one it is looking at. A consumer that
      means "is this instance ready" should read the honest key.

    Args:
        version: Version of the AS.
        uptime_seconds: Seconds since process start.
        screening_data_loaded: Whether screening data is active.
        instance: Machine identity of the instance answering; defaults to this module's.

    Returns:
        The health document served on ``GET /healthz``.
    """
    return {
        "status": "ok" if screening_data_loaded else "degraded",
        "instance": instance,
        "version": version,
        "uptime_seconds": round(uptime_seconds, 3),
        "rule_set_loaded": screening_data_loaded,
        "screening_data_loaded": screening_data_loaded,
    }


def metrics_payload(registry: MetricsRegistry) -> dict[str, Any]:
    """Build the statistics payload from the counter registry.

    The keys match the number-translation AS's payload so the existing console statistics
    view renders either instance; ``rule_hits`` is always empty here and the screening
    verdicts arrive through ``counters``.

    Args:
        registry: The metrics registry of the anti-fraud process.

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
        "counters": snapshot.counters,
    }


def _entry_payload(entry: ListMatch) -> dict[str, Any]:
    """Serialise one block/allow-list entry.

    Args:
        entry: The matched entry view with its derived identifier.

    Returns:
        A JSON-serialisable representation of the entry.
    """
    return {"entry_id": entry.entry_id, "value": entry.value, "reason": entry.reason}


def screening_payload(store: ScreeningDataStore) -> dict[str, Any]:
    """Build the read-only screening-data payload for the console.

    Args:
        store: The active screening-data store.

    Returns:
        The document served on ``GET /api/v1/screening``.
    """
    data = store.current
    document = data.document
    return {
        "source": str(data.source),
        "name": document.name,
        "description": document.description,
        "version": document.version,
        "window": {
            "seconds": document.window.seconds,
            "max_calls": document.window.max_calls,
        },
        "reputation": {
            "half_life_seconds": document.reputation.half_life_seconds,
            "default_score": document.reputation.default_score,
            "reject_below": document.reputation.reject_below,
            "reject_penalty": document.reputation.reject_penalty,
            "max_tracked_callers": document.reputation.max_tracked_callers,
        },
        "block_list": [_entry_payload(entry) for entry in data.block_entries()],
        "allow_list": [_entry_payload(entry) for entry in data.allow_entries()],
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
        recorder: The trace recorder of the anti-fraud process.
        limit: Maximum number of calls to include.

    Returns:
        The document served on ``GET /api/v1/traces``.
    """
    return {"calls": [trace_payload(trace) for trace in recorder.recent(limit)]}


def create_internal_api_app(
    *,
    version: str,
    screening_data_store: ScreeningDataStore,
    metrics: MetricsRegistry,
    tracer: TraceRecorder,
    started_at: float,
) -> FastAPI:
    """Create the FastAPI application for the anti-fraud internal API.

    Args:
        version: Version reported by the health endpoint.
        screening_data_store: Source of the active screening data, reported as readiness.
        metrics: Counter registry exposed on ``/api/v1/metrics``.
        tracer: Trace recorder exposed on ``/api/v1/traces``.
        started_at: ``time.monotonic()`` value at server creation, for uptime.

    Returns:
        A FastAPI application with the anti-fraud routes.
    """
    app = FastAPI(title="anti-fraud AS internal API", version=version)

    # Loopback-only demo surface, reached from a different port (ADR-0002, gaps accepted).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        """Liveness and readiness of the anti-fraud AS process.

        Returns:
            The health document with status, version, uptime and screening-data state.
        """
        return health_payload(
            version=version,
            uptime_seconds=time.monotonic() - started_at,
            screening_data_loaded=screening_data_store.current is not None,
        )

    @app.get("/api/v1/metrics")
    def get_metrics() -> dict[str, Any]:
        """Counters, verdicts, error codes and peer status.

        Returns:
            The metrics snapshot document.
        """
        return metrics_payload(metrics)

    @app.get("/api/v1/screening")
    def get_screening() -> dict[str, Any]:
        """The active screening data, read-only.

        Returns:
            The screening document, or a 503 when no screening data is loaded.
        """
        if screening_data_store.current is None:
            return JSONResponse({"error": "no screening data loaded"}, status_code=503)
        return screening_payload(screening_data_store)

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
                    await websocket.send_json(
                        {
                            "type": "traces",
                            "traces": [trace_payload(t) for t in recent if t.call_id in new_ids],
                        }
                    )
                    seen_call_ids = current_ids
        except WebSocketDisconnect:
            pass

    return app


class InternalApiServer:
    """FastAPI/uvicorn internal API server running on a daemon thread.

    Served from a daemon thread with its own asyncio event loop, so it never blocks the
    sippy event loop (ADR-0002). Every route handler reads lock-guarded snapshots.

    Attributes:
        address: Local address the server binds.
        port: Local TCP port the server binds.
        version: Version reported by the health endpoint.
        screening_data_store: Source of the active screening data, reported as readiness.
        metrics: Counter registry exposed on ``/api/v1/metrics``.
        tracer: Trace recorder exposed on ``/api/v1/traces``.
    """

    def __init__(
        self,
        address: str,
        port: int,
        *,
        version: str,
        screening_data_store: ScreeningDataStore,
        metrics: MetricsRegistry,
        tracer: TraceRecorder,
    ) -> None:
        """Create the internal API server.

        Args:
            address: Local address to bind.
            port: Local TCP port to bind.
            version: Version reported by the health endpoint.
            screening_data_store: Source of the active screening data.
            metrics: Counter registry.
            tracer: Trace recorder.
        """
        self.address = address
        self.port = port
        self.version = version
        self.screening_data_store = screening_data_store
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
        import uvicorn  # imported lazily: only the process runs the server

        app = create_internal_api_app(
            version=self.version,
            screening_data_store=self.screening_data_store,
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
        self._thread = threading.Thread(
            target=self._server.run, name="fraud-internal-api", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._server = None
