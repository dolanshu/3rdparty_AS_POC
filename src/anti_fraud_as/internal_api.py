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

Its own process, its own API, its own port (ADR-0002, ADR-0007 decision 9). The shared
mechanism — the app factory, the daemon-thread server and the payload builders that are not
bound to this use case — lives in the platform library (``as_platform.internal_api``). This
module keeps the anti-fraud AS's own parts: its instance identity, its route table, its
health document and the one resource route typed on this repository's
:class:`~anti_fraud_as.screening_data.ScreeningDataStore` (ADR-0009 decision 2). The library
factory is generalised over a :class:`~as_platform.internal_api.PayloadProvider`, so nothing
here or there branches on "which application am I".

``metrics_payload``, ``trace_payload`` and ``traces_payload`` are re-exports of the library's,
kept so every reference by path — in ``tests/``, ``tools/`` and the docs — keeps resolving.

Endpoints (ADR-0002)::

    GET /healthz                     — liveness and readiness
    GET /api/v1/metrics              — counters, verdicts, error codes, peer status
    GET /api/v1/screening            — block/allow lists and window/reputation parameters
    GET /api/v1/traces               — most recent calls with their trace events
    GET /api/v1/traces/{call_id}     — one call, Call-ID keyed
    GET /api/v1/traces/{call_id}/messages — verbatim SIP for trunk + outbound legs
    WS  /ws/events                   — live event feed for the console
"""

from __future__ import annotations

import threading
from typing import Any, Final

from as_platform.internal_api import InternalApiServer as _InternalApiServer
from as_platform.internal_api import create_internal_api_app as _create_internal_api_app
from as_platform.internal_api import health_payload as _health_payload
from as_platform.internal_api import (
    messages_payload,
    metrics_payload,
    trace_payload,
    traces_payload,
)
from as_platform.observability.metrics import MetricsRegistry
from as_platform.observability.tracing import SipMessageRecorder, TraceRecorder
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from anti_fraud_as.screening_data import ListMatch, ScreeningDataStore

__all__ = [
    "INSTANCE_NAME",
    "INTERNAL_API_ROUTES",
    "InternalApiServer",
    "create_internal_api_app",
    "health_payload",
    "messages_payload",
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
    "GET /api/v1/traces/{call_id}/messages": "verbatim SIP for trunk and outbound legs",
    "WS /ws/events": "live event feed for the console",
}


class _ScreeningPayloadProvider:
    """The anti-fraud AS's data for the shared internal API shell.

    Screening data is this instance's readiness source and its one resource route, so the
    provider is the whole seam between the library factory and the AS (ADR-0009 decision 2).
    """

    #: Machine identity reported on ``GET /healthz``.
    instance = INSTANCE_NAME

    #: FastAPI application title.
    title = "anti-fraud AS internal API"

    #: Name of the uvicorn daemon thread.
    thread_name = "fraud-internal-api"

    #: The one resource route this instance serves.
    resource_path = "/api/v1/screening"

    #: The 503 error text when no screening data is loaded.
    resource_missing = "no screening data loaded"

    def __init__(self, store: ScreeningDataStore) -> None:
        """Create the provider around the AS's screening-data store.

        Args:
            store: Source of the active screening data.
        """
        self._store = store

    @property
    def ready(self) -> bool:
        """Whether screening data is active."""
        return self._store.current is not None

    def health_extra(self) -> dict[str, Any]:
        """Return the extra health keys this instance adds.

        Returns:
            The honest readiness key of this instance, reported beside the shared
            compatibility key.
        """
        return {"screening_data_loaded": self._store.current is not None}

    def resource(self) -> dict[str, Any] | None:
        """Return the active screening data as a console payload.

        Returns:
            The screening document, or ``None`` when no screening data is loaded.
        """
        if self._store.current is None:
            return None
        return screening_payload(self._store)


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
    return _health_payload(
        version=version,
        uptime_seconds=uptime_seconds,
        ready=screening_data_loaded,
        instance=instance,
        extra={"screening_data_loaded": screening_data_loaded},
    )


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


def create_internal_api_app(
    *,
    version: str,
    screening_data_store: ScreeningDataStore,
    metrics: MetricsRegistry,
    tracer: TraceRecorder,
    sip_recorder: SipMessageRecorder | None = None,
    started_at: float,
) -> FastAPI:
    """Create the FastAPI application for the anti-fraud internal API.

    Args:
        version: Version reported by the health endpoint.
        screening_data_store: Source of the active screening data, reported as readiness.
        metrics: Counter registry exposed on ``/api/v1/metrics``.
        tracer: Trace recorder exposed on ``/api/v1/traces``.
        sip_recorder: Verbatim SIP recorder for ``/api/v1/traces/{call_id}/messages``.
        started_at: ``time.monotonic()`` value at server creation, for uptime.

    Returns:
        A FastAPI application with the anti-fraud routes.
    """
    return _create_internal_api_app(
        version=version,
        provider=_ScreeningPayloadProvider(screening_data_store),
        metrics=metrics,
        tracer=tracer,
        started_at=started_at,
        sip_recorder=sip_recorder,
    )


class SimplePublisher:
    """Asyncio-friendly WebSocket fanout for P12 event emission."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """Accept and track one WebSocket connection."""
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove one WebSocket from the fanout."""
        self._connections.discard(ws)

    async def broadcast(self, message: str) -> None:
        """Send one message to every connected WebSocket."""
        if not self._connections:
            return
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def _mount_p12_fanout(app: FastAPI, publisher: SimplePublisher) -> None:
    """Attach the P12 event fanout and its WebSocket endpoint to ``app``."""
    app.state.publisher = publisher
    app.state.broadcast = publisher.broadcast  # type: ignore[attr-defined]

    @app.websocket("/ws/p12/events")
    async def p12_events(ws: WebSocket) -> None:
        """Live P12 event feed (push fanout, not polling)."""
        await publisher.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            publisher.disconnect(ws)


class InternalApiServer(_InternalApiServer):
    """FastAPI/uvicorn internal API server running on a daemon thread.

    Overrides :meth:`start` to build the FastAPI app eagerly, mount the P12
    broadcast fanout and expose the app on :attr:`app` before uvicorn starts —
    so the call controller can reference ``app.state.broadcast`` from the sippy
    thread (P12, REQ-F-042).

    Attributes:
        address: Local address the server binds.
        port: Local TCP port the server binds.
        version: Version reported by the health endpoint.
        screening_data_store: Source of the active screening data.
        metrics: Counter registry exposed on ``/api/v1/metrics``.
        tracer: Trace recorder exposed on ``/api/v1/traces``.
        app: The FastAPI application, available after construction.
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
        sip_recorder: SipMessageRecorder | None = None,
    ) -> None:
        """Create the internal API server.

        Args:
            address: Local address to bind.
            port: Local TCP port to bind.
            version: Version reported by the health endpoint.
            screening_data_store: Source of the active screening data.
            metrics: Counter registry.
            tracer: Trace recorder.
            sip_recorder: Verbatim SIP recorder for the messages route.
        """
        self.screening_data_store = screening_data_store
        # Eagerly build the app + P12 fanout so call_map can access ``.app``
        # before ``start()`` is called on the daemon thread.
        import time as _time

        self.app = create_internal_api_app(
            version=version,
            screening_data_store=screening_data_store,
            metrics=metrics,
            tracer=tracer,
            sip_recorder=sip_recorder,
            started_at=_time.monotonic(),
        )
        _mount_p12_fanout(self.app, SimplePublisher())
        super().__init__(
            address,
            port,
            version=version,
            provider=_ScreeningPayloadProvider(screening_data_store),
            metrics=metrics,
            tracer=tracer,
            sip_recorder=sip_recorder,
        )

    def start(self) -> None:
        """Bind the port and serve in the background on a daemon thread."""
        import uvicorn

        def _daemon_run() -> None:
            import asyncio as _asyncio

            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            self._loop = loop
            self.app.state._loop = loop

            config = uvicorn.Config(
                self.app,
                host=self.address,
                port=self.port,
                log_level="error",
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._server.run()

        self._thread = threading.Thread(
            target=_daemon_run, name=self.provider.thread_name, daemon=True
        )
        self._thread.start()
