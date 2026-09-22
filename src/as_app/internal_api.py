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

"""Internal REST and WebSocket surface of the number-translation AS.

The shared mechanism — the app factory, the daemon-thread server and the payload builders
that are not bound to this use case — lives in the platform library
(``as_platform.internal_api``). This module keeps the number-translation AS's own parts: its
instance identity, its route table, its health document and the one resource route typed on
this repository's :class:`~as_app.routing.rules.RuleSet` (ADR-0009 decision 2). The library
factory is generalised over a :class:`~as_platform.internal_api.PayloadProvider`, so nothing
here or there branches on "which application am I".

``metrics_payload``, ``trace_payload`` and ``traces_payload`` are re-exports of the library's,
kept so every reference by path — in ``tests/``, ``tools/`` and the docs — keeps resolving.

Endpoints (ADR-0002)::

    GET /healthz                   — liveness and readiness
    GET /api/v1/metrics            — counters, dispositions, rule hits, peer status
    GET /api/v1/rules              — active rule set, read-only
    GET /api/v1/traces             — most recent calls with their trace events
    GET /api/v1/traces/{call_id}   — one call, Call-ID keyed
    WS  /ws/events                 — live event feed for the console
"""

from __future__ import annotations

import threading
from typing import Any, Final

from as_platform.internal_api import InternalApiServer as _InternalApiServer
from as_platform.internal_api import create_internal_api_app as _create_internal_api_app
from as_platform.internal_api import health_payload as _health_payload
from as_platform.internal_api import metrics_payload, trace_payload, traces_payload
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from as_app.observability.metrics import MetricsRegistry
from as_app.observability.tracing import TraceRecorder
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


class _RuleSetPayloadProvider:
    """The number-translation AS's data for the shared internal API shell.

    The rule set is this instance's readiness source and its one resource route, so the
    provider is the whole seam between the library factory and the AS (ADR-0009 decision 2).
    """

    #: Machine identity reported on ``GET /healthz``.
    instance = INSTANCE_NAME

    #: FastAPI application title.
    title = "3rd-party AS internal API"

    #: Name of the uvicorn daemon thread.
    thread_name = "internal-api"

    #: The one resource route this instance serves.
    resource_path = "/api/v1/rules"

    #: The 503 error text when no rule set is loaded.
    resource_missing = "no rule set loaded"

    def __init__(self, store: RuleSetStore) -> None:
        """Create the provider around the AS's rule set store.

        Args:
            store: Source of the active rule set.
        """
        self._store = store

    @property
    def ready(self) -> bool:
        """Whether a rule set is active."""
        return self._store.current is not None

    def health_extra(self) -> dict[str, Any]:
        """Return the extra health keys this instance adds.

        Returns:
            An empty mapping: the number-translation AS reports only the shared keys.
        """
        return {}

    def resource(self) -> dict[str, Any] | None:
        """Return the active rule set as a console payload.

        Returns:
            The rules document, or ``None`` when no rule set is loaded.
        """
        rule_set = self._store.current
        if rule_set is None:
            return None
        return rules_payload(rule_set)


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
    return _health_payload(
        version=version,
        uptime_seconds=uptime_seconds,
        ready=rule_set_loaded,
        instance=instance,
    )


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


def create_internal_api_app(
    *,
    version: str,
    rule_set_store: RuleSetStore,
    metrics: MetricsRegistry,
    tracer: TraceRecorder,
    started_at: float,
) -> FastAPI:
    """Create the FastAPI application for the internal API.

    Args:
        version: Version reported by the health endpoint.
        rule_set_store: Source of the active rule set, reported as readiness.
        metrics: Counter registry exposed on ``/api/v1/metrics``.
        tracer: Trace recorder exposed on ``/api/v1/traces``.
        started_at: ``time.monotonic()`` value at server creation, for uptime.

    Returns:
        A FastAPI application with the internal API routes.
    """
    return _create_internal_api_app(
        version=version,
        provider=_RuleSetPayloadProvider(rule_set_store),
        metrics=metrics,
        tracer=tracer,
        started_at=started_at,
    )


class SimplePublisher:
    """Asyncio-friendly WebSocket fanout for P12 event emission.

    Kept as a tiny class rather than importing from a pubsub library: the AS
    has at most one or two console connections (ADR-0002), so a set of
    WebSockets and one ``asyncio.Queue``-less broadcast is enough.
    """

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
    """Attach the P12 event fanout and its WebSocket endpoint to ``app``.

    Called after :func:`create_internal_api_app` so the parent routes (health,
    metrics, traces, ...) are already in place; P12 adds only the broadcast
    mechanism and its own WebSocket path.
    """
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

    The public constructor is this instance's: it takes the rule set store the
    number-translation AS serves and binds it to the shared server through the provider.

    Overrides :meth:`start` to build the FastAPI app eagerly, mount the P12
    broadcast fanout and expose the app on :attr:`app` before uvicorn starts —
    so the call controller can reference ``app.state.broadcast`` from the sippy
    thread (P12, REQ-F-042).

    Attributes:
        address: Local address the server binds.
        port: Local TCP port the server binds.
        version: Version reported by the health endpoint.
        rule_set_store: Source of the active rule set, reported as readiness.
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
        self.rule_set_store = rule_set_store
        # Eagerly build the app + P12 fanout so call_map can access ``.app``
        # before ``start()`` is called on the daemon thread.
        import time as _time

        self.app = create_internal_api_app(
            version=version,
            rule_set_store=rule_set_store,
            metrics=metrics,
            tracer=tracer,
            started_at=_time.monotonic(),  # real monotonic for health uptime
        )
        _mount_p12_fanout(self.app, SimplePublisher())
        super().__init__(
            address,
            port,
            version=version,
            provider=_RuleSetPayloadProvider(rule_set_store),
            metrics=metrics,
            tracer=tracer,
        )

    def start(self) -> None:
        """Bind the port and serve in the background on a daemon thread.

        Creates a dedicated event loop on the daemon thread so call controllers
        (which run on the sippy main thread) can schedule broadcast coroutines
        via ``run_coroutine_threadsafe`` against a known, running loop.
        """
        import uvicorn

        def _daemon_run() -> None:
            import asyncio as _asyncio

            # CRITICAL: uvicorn.Server.run() internally calls asyncio.run() which
            # ALWAYS creates a fresh event loop — it ignores any set_event_loop()
            # we do here. So we bypass uvicorn.run() entirely and drive the loop
            # ourselves so that app.state._loop = this_loop (one and the same)
            # and run_coroutine_threadsafe() submissions actually execute.
            #
            # See: https://github.com/encode/uvicorn/issues/1627
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

            try:
                loop.run_until_complete(self._server.serve())
            finally:
                loop.close()

        self._thread = threading.Thread(
            target=_daemon_run, name=self.provider.thread_name, daemon=True
        )
        self._thread.start()
