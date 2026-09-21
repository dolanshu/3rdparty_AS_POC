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

"""Interactive SIP load generator — P12 Call Load capability.

Standalone Python process that does **not** import ``as_platform``,
``src/as_app`` or ``src/anti_fraud_as`` (REQ-NF-029). Talks to AS processes
via real SIP INVITEs on their configured listen port and observes via
WebSocket event streams. See ``docs/architecture/hld.md`` section 12 and
``docs/architecture/lld.md`` section 12 for the design.

This module contains the full generator: data models, pool management,
MockSipUac skeleton, and FastAPI REST/WebSocket surface.
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Final


# ======================================================================
# Call type model
# ======================================================================


class CallModel:
    """Weighted-random selection across the 10 call types.

    Every type has equal base weight; toggling is handled by passing the
    enabled subset to :meth:`pick`. All constants are ``Final`` class attrs
    so the values used in tests are the same values used in production
    (no magic numbers duplicated).
    """

    ALL_TYPES: Final[frozenset[str]] = frozenset(
        {f"T{i}" for i in range(1, 7)} | {f"F{i}" for i in range(1, 5)}
    )

    _base_weights: Final[dict[str, float]] = {t: 1.0 for t in ALL_TYPES}

    @classmethod
    def pick(cls, enabled_types: set[str]) -> str:
        """Return one call type from the enabled set via weighted random.

        Args:
            enabled_types: Subset of :attr:`ALL_TYPES` the caller has toggled on.

        Raises:
            ValueError: When ``enabled_types`` is empty or contains unknown keys.
        """
        if not enabled_types:
            raise ValueError("enabled_call_types must not be empty")
        unknown = enabled_types - cls.ALL_TYPES
        if unknown:
            raise ValueError(f"Unknown call types: {sorted(unknown)}")
        keys = sorted(enabled_types)
        weights = [cls._base_weights[t] for t in keys]
        return random.choices(keys, weights=weights, k=1)[0]


# ======================================================================
# Duration model
# ======================================================================


class DurationModel:
    """Fixed-weight duration classes (HLD §12.4, REQ-F-041)."""

    WEIGHTS: Final[dict[str, float]] = {
        "D1": 0.30,  # Fast: ~2 s conversation
        "D2": 0.50,  # Medium: ~8–15 s conversation
        "D3": 0.15,  # Long: ~20–30 s conversation
        "D4": 0.05,  # Timeout: AS tears down on 3 s timer
    }

    #: Midpoint BYE timing for each class (seconds after 200 OK).
    MIDPOINTS: Final[dict[str, float]] = {
        "D1": 2.5,
        "D2": 11.5,
        "D3": 25.0,
        "D4": 3.0,
    }

    #: Weight-derived average duration — used for Little's Law coupling.
    #: Design constant (ADR-0013), not a runtime measurement.
    AVG_DURATION_SECONDS: Final[float] = (
        0.30 * 2.5 + 0.50 * 11.5 + 0.15 * 25.0 + 0.05 * 3.0
    )  # = 9.5

    @classmethod
    def pick(cls) -> str:
        """Return one duration class via weighted random."""
        keys = sorted(cls.WEIGHTS.keys())
        weights = [cls.WEIGHTS[k] for k in keys]
        return random.choices(keys, weights=weights, k=1)[0]


# ======================================================================
# Configuration and per-call state
# ======================================================================


@dataclass(frozen=True)
class PoolConfig:
    """Immutable pool configuration — validated once at construction."""

    target_concurrency: int
    call_rate: float
    enabled_call_types: frozenset[str]

    def __post_init__(self) -> None:
        if not (1 <= self.target_concurrency <= 50):
            raise ValueError(
                f"target_concurrency must be 1..50, got {self.target_concurrency}"
            )
        if not (0.1 <= self.call_rate <= 10.0):
            raise ValueError(f"call_rate must be 0.1..10.0, got {self.call_rate}")
        if not self.enabled_call_types:
            raise ValueError("enabled_call_types must not be empty")
        unknown = self.enabled_call_types - CallModel.ALL_TYPES
        if unknown:
            raise ValueError(f"Unknown call types: {sorted(unknown)}")


@dataclass
class CallInstance:
    """One call being driven by the generator."""

    call_id: str
    call_type: str
    duration_class: str
    state: str
    far_end_behavior: str
    started_at: float
    ended_at: float | None = None


# ======================================================================
# CallPool — leaky-bucket concurrency pool with refill throttle
# ======================================================================


class CallPool:
    """Closed-loop concurrency pool with open-loop rate throttle.

    Two controls interact via Little's Law (`L = λW`; ADR-0013) — the
    :meth:`compute_binding_constraint` method tells which control is
    currently limiting the pool and is exposed on ``/load/status``.

    Tick loop runs every :data:`TICK_INTERVAL` seconds; rate budget resets
    every :data:`RATE_BUDGET_RESET_INTERVAL` seconds. Call completion is
    signalled via :meth:`_on_call_ended`, which bridges from a potentially
    non-asyncio context (sippy thread) to the pool's asyncio loop.
    """

    TICK_INTERVAL: Final[float] = 0.5
    RATE_BUDGET_RESET_INTERVAL: Final[float] = 1.0

    def __init__(self, config: PoolConfig, mock_uac: Any | None = None) -> None:
        self._config = config
        self._mock_uac = mock_uac
        self._lock = asyncio.Lock()
        self.active_calls: int = 0
        self.active_instances: dict[str, CallInstance] = {}
        self._rate_budget: float = config.call_rate
        self._last_budget_reset: float = time.monotonic()
        self._running: bool = False
        self._tick_task: asyncio.Task[None] | None = None

    # --------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------

    async def start(self) -> None:
        """Start the tick loop. First tick fires after TICK_INTERVAL ms."""
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Stop the tick loop. Active calls are not force-terminated."""
        self._running = False
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None

    async def set_config(self, config: PoolConfig) -> None:
        """Apply new config on the next tick; already-running calls unaffected."""
        async with self._lock:
            self._config = config
            self._rate_budget = config.call_rate
            self._last_budget_reset = time.monotonic()

    # --------------------------------------------------------------
    # Query
    # --------------------------------------------------------------

    def active_count(self) -> int:
        return self.active_calls

    def compute_binding_constraint(self) -> str:
        """Return ``'concurrency'`` or ``'rate'`` (ADR-0013)."""
        theoretical = self._config.call_rate * DurationModel.AVG_DURATION_SECONDS
        if theoretical >= self._config.target_concurrency:
            return "concurrency"
        return "rate"

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot (for ``/load/status``)."""
        return {
            "active_calls": self.active_calls,
            "target_concurrency": self._config.target_concurrency,
            "call_rate": self._config.call_rate,
            "binding_constraint": self.compute_binding_constraint(),
            "enabled_call_types": sorted(self._config.enabled_call_types),
            "rate_budget_remaining": round(self._rate_budget, 2),
        }

    # --------------------------------------------------------------
    # Internal — tick loop
    # --------------------------------------------------------------

    async def _tick_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.TICK_INTERVAL)
            await self._tick()

    async def _tick(self) -> None:
        # 1. Reset rate budget every full second
        now = time.monotonic()
        elapsed = now - self._last_budget_reset
        if elapsed >= self.RATE_BUDGET_RESET_INTERVAL:
            self._rate_budget = self._config.call_rate
            self._last_budget_reset = now
            # Allow fractional budget from partial-second overshoot in the
            # tick that crosses the boundary — this models "refill every
            # second" rather than "proportional refill every half-second".

        # 2. Critical section — check pool + launch
        async with self._lock:
            deficit = self._config.target_concurrency - self.active_calls
            if deficit <= 0 or self._rate_budget <= 0:
                return

            new_count = min(deficit, int(self._rate_budget))
            for _ in range(new_count):
                await self._spawn_one()
                self._rate_budget -= 1.0

    async def _spawn_one(self) -> None:
        call_type = CallModel.pick(self._config.enabled_call_types)
        duration_class = DurationModel.pick()
        call_id = f"gen-{uuid.uuid4().hex[:12]}"
        behavior = "timeout_no_answer" if duration_class == "D4" else "answer_and_bye"

        if self._mock_uac is not None:
            # Make sure _on_call_ended is a plain callable (asyncio bridge inside)
            self._mock_uac.set_loop(asyncio.get_event_loop())
            await self._mock_uac.send_invite(
                call_id=call_id,
                call_type=call_type,
                duration_class=duration_class,
                on_call_ended=self._on_call_ended,
            )

        self.active_instances[call_id] = CallInstance(
            call_id=call_id,
            call_type=call_type,
            duration_class=duration_class,
            state="invited",
            far_end_behavior=behavior,
            started_at=time.monotonic(),
        )
        self.active_calls += 1

    # --------------------------------------------------------------
    # Call completion — bridges from (potentially) non-asyncio context
    # --------------------------------------------------------------

    def _on_call_ended(self, call_id: str, reason: str) -> None:
        """Called by MockSipUac when a call ends.

        May fire from a thread that is not the asyncio loop thread
        (e.g. sippy's internal callback thread). Bridge safely to the
        loop via :func:`asyncio.run_coroutine_threadsafe`.
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return  # no event loop — shouldn't happen in production
        if asyncio.get_running_loop() is loop:
            # Already on the loop thread — schedule a task
            loop.create_task(self._async_on_call_ended(call_id, reason))
        else:
            asyncio.run_coroutine_threadsafe(
                self._async_on_call_ended(call_id, reason), loop
            )

    async def _async_on_call_ended(self, call_id: str, reason: str) -> None:
        async with self._lock:
            if call_id in self.active_instances:
                del self.active_instances[call_id]
                self.active_calls -= 1
            # Task 4 will emit generator-side call_ended and pool_status_update here.


# ======================================================================
# MockSipUac — standalone SIP UAC (sippy-based, runs on same asyncio loop)
# ======================================================================


class MockSipUac:
    """Sends real SIP INVITEs to an AS and controls far-end behaviour.

    Reuses the :class:`sippy.UA` pattern from ``src/s_sbc_mock/uac.py``
    but runs as a standalone process (ADR-0012). Duration-class-controlled
    far-end behaviour is added here — the s_sbc_mock UAC has no concept
    of "answer then BYE after N seconds" vs "never answer".
    """

    #: sippy imports are optional — they're only needed when actually
    #: driving SIP. Unit tests use :class:`_FakeUac` instead.
    _sippy_available: bool = False

    def __init__(self, as_address: str, as_port: int,
                 local_address: str = "127.0.0.1", local_port: int = 5099) -> None:
        self.as_address = as_address
        self.as_port = as_port
        self.local_address = local_address
        self.local_port = local_port
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def send_invite(
        self, *, call_id: str, call_type: str,
        duration_class: str,
        on_call_ended: Callable[[str, str], None],
    ) -> None:
        """Send one SIP INVITE to the AS (stubbed — full sippy integration
        deferred to Task 10 e2e).
        """
        if self._sippy_available:
            self._send_invite_real(call_id, call_type, duration_class, on_call_ended)
        # Stubbed — Task 10 implements real sippy UAC creation and SIP send.

    # ------------------------------------------------------------------
    # Number selection per call type
    # ------------------------------------------------------------------

    def numbers_for(self, call_type: str) -> tuple[str, str]:
        """Return ``(called, caller)`` for a call type (HLD §12.3)."""
        table: dict[str, tuple[str, str]] = {
            "T1": ("+8613800138000", "1001"),          # E.164 → translation
            "T2": ("02112345678", "1001"),              # national
            "T3": ("0014155551234", "1001"),            # international
            "T4": ("1234", "1001"),                     # short code → 404
            "T5": ("+8613900139000", "1001"),           # reachable next hop
            "T6": ("+8613700137000", "1001"),           # unreachable next hop
            "F1": ("+8613800138000", "1001"),           # allow-listed
            "F2": ("+8613800138000", "1999"),           # block-listed → 608
            "F3": ("+8613800138000", "1998"),           # high-rate window → 608
            "F4": ("+8613800138000", "1001"),           # missing PAI → fail-open
        }
        if call_type not in table:
            raise ValueError(f"Unknown call type: {call_type}")
        return table[call_type]

    # ------------------------------------------------------------------
    # Real sippy UAC send (stubbed — activated when sippy is available)
    # ------------------------------------------------------------------

    def _send_invite_real(self, call_id: str, call_type: str,
                           duration_class: str,
                           on_end: Callable[[str, str], None]) -> None:
        raise NotImplementedError(
            "Full sippy UAC send deferred to Task 10 (e2e integration). "
            f"Numbers selected: {self.numbers_for(call_type)}, "
            f"duration_class={duration_class}."
        )


# ======================================================================
# REST API — FastAPI application builder
# ======================================================================

try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


if FASTAPI_AVAILABLE:

    class _LoadConfigRequest(BaseModel):
        target_concurrency: int = Field(ge=1, le=50)
        call_rate: float = Field(ge=0.1, le=10.0)
        enabled_call_types: list[str]

    def build_generator_app(
        *,
        pool_state_getter: Callable[[], dict[str, Any]] | None = None,
        pool_controller: Callable[[str, PoolConfig | None], Any] | None = None,
    ) -> FastAPI:
        """Build the generator's FastAPI REST + WebSocket application.

        Args:
            pool_state_getter: Called on every ``GET /load/status`` to read
                pool snapshot. When ``None``, returns static defaults (tests).
            pool_controller: Called with ``(action, config_or_None)`` on
                start/stop/config. Action is one of ``"start"``, ``"stop"``,
                ``"config"``. When ``None``, endpoints return success without
                mutating state (tests).
        """
        app = FastAPI(title="Call Load Generator", version="1.0.0")

        # CORS open — same reason as AS's internal API (ADR-0002)
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        def _default_getter() -> dict[str, Any]:
            return {
                "active_calls": 0,
                "target_concurrency": 10,
                "call_rate": 3.0,
                "binding_constraint": "concurrency",
                "enabled_call_types": sorted(CallModel.ALL_TYPES),
                "rate_budget_remaining": 3.0,
            }

        @app.get("/load/status")
        async def get_status():
            return (pool_state_getter or _default_getter)()

        @app.post("/load/start")
        async def start_load():
            if pool_controller:
                result = pool_controller("start", None)
                return {"status": "started", "detail": result}
            return {"status": "started"}

        @app.post("/load/stop")
        async def stop_load():
            if pool_controller:
                result = pool_controller("stop", None)
                return {"status": "stopped", "detail": result}
            return {"status": "stopped"}

        @app.put("/load/config")
        async def set_config(req: _LoadConfigRequest):
            try:
                enabled = frozenset(req.enabled_call_types)
                config = PoolConfig(
                    target_concurrency=req.target_concurrency,
                    call_rate=req.call_rate,
                    enabled_call_types=enabled,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            if pool_controller:
                pool_controller("config", config)
            return {"status": "configured", "config": req.model_dump()}

        @app.websocket("/ws/pool")
        async def pool_feed(ws: WebSocket):
            """Push ``pool_status_update`` events to connected clients."""
            await ws.accept()
            try:
                while True:
                    snapshot = (pool_state_getter or _default_getter)()
                    await ws.send_json({
                        "timestamp": time.time(),
                        "source": "load_generator",
                        "event": "pool_status_update",
                        "attributes": snapshot,
                    })
                    await asyncio.sleep(1.0)
            except WebSocketDisconnect:
                pass

        return app
