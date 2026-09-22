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

import argparse
import asyncio
import random
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final

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

    _base_weights: Final[dict[str, float]] = dict.fromkeys(ALL_TYPES, 1.0)

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
        self._loop: asyncio.AbstractEventLoop | None = None
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
        self._loop = asyncio.get_running_loop()
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Stop the tick loop and force-terminate all active calls.

        The tick loop is cancelled first so no new INVITEs go out, then
        every in-flight call on the MockSipUac is told to BYE immediately.
        Active calls drain to zero over the next 1–2 pool_status_update
        ticks as the BYEs round-trip through AS and the far-end core mock.
        """
        self._running = False
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None
        # Force BYE every in-flight call — bridges to the sippy ED2 thread
        # internally, so this is safe to call from the asyncio loop.
        if self._mock_uac is not None:
            self._mock_uac.force_disconnect_all()

    async def set_config(self, config: PoolConfig) -> None:
        """Apply new config on the next tick; already-running calls unaffected."""
        async with self._lock:
            self._config = config
            self._rate_budget = config.call_rate
            self._last_budget_reset = time.monotonic()

    # --------------------------------------------------------------
    # Query
    # --------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the tick loop is active (public for external controllers)."""
        return self._running

    def active_count(self) -> int:
        return self.active_calls

    def compute_binding_constraint(self) -> str:
        """Return ``'concurrency'`` or ``'rate'`` (ADR-0013)."""
        theoretical = self._config.call_rate * DurationModel.AVG_DURATION_SECONDS
        if theoretical >= self._config.target_concurrency:
            return "concurrency"
        return "rate"

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot (for ``/load/status`` and WS)."""
        return {
            "running": self.is_running,
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
        loop = self._loop
        if loop is None:
            return  # loop not ready — shouldn't happen in production
        # run_coroutine_threadsafe is safe from any thread, including
        # the ED2 thread that has no asyncio loop of its own.
        try:
            asyncio.run_coroutine_threadsafe(
                self._async_on_call_ended(call_id, reason), loop
            )
        except RuntimeError:
            return  # loop closed during bridge

    async def _async_on_call_ended(self, call_id: str, reason: str) -> None:
        async with self._lock:
            if call_id in self.active_instances:
                del self.active_instances[call_id]
                self.active_calls -= 1


# ======================================================================
# MockSipUac — standalone SIP UAC (sippy-based, runs on dedicated thread)
# ======================================================================


#: POC domain used in generator SIP headers (RFC 2606, RFC 6761).
_IMS_DOMAIN = "ims.example.invalid"

#: Plain G.711 offer shared with the mock S-SBC (tools/call_load_generator.py
#: imports it so both UAC sides generate the same SDP — pass-through proof).
DEFAULT_SDP_OFFER = "\r\n".join(
    [
        "v=0",
        "o=- 4101 4101 IN IP4 192.0.2.10",
        "s=3rd-party AS POC call",
        "c=IN IP4 192.0.2.10",
        "t=0 0",
        "m=audio 40000 RTP/AVP 0 8 101",
        "a=rtpmap:0 PCMU/8000",
        "a=rtpmap:8 PCMA/8000",
        "a=rtpmap:101 telephone-event/8000",
        "a=fmtp:101 0-15",
        "a=sendrecv",
        "",
    ]
)


class MockSipUac:
    """Sends real SIP INVITEs to an AS and controls far-end behaviour.

    Runs its own :class:`sippy.SipTransactionManager` on a dedicated daemon
    thread with :class:`sippy.Core.EventDispatcher.ED2.loop()` (ADR-0012).
    :meth:`send_invite` runs on the asyncio loop and bridges into sippy's
    thread via :class:`sippy.Time.Timeout.Timeout`; sippy events bridge back
    via :func:`asyncio.run_coroutine_threadsafe`.

    Duration-class-controlled far-end behaviour:

    * **D1/D2/D3** — AS answers 200 OK, UAC waits MIDPOINT seconds then sends BYE.
    * **D4** — AS never answers; no-answer timer expires, UAC tears down via CANCEL.
    """

    #: sippy imports happen at use-site so tests importing this module don't
    #: need sippy installed; the generator process always has sippy.

    def __init__(
        self,
        as_address: str,
        as_port: int,
        local_address: str = "127.0.0.1",
        local_port: int = 5099,
    ) -> None:
        self.as_address = as_address
        self.as_port = as_port
        self.local_address = local_address
        self.local_port = local_port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._global_config: dict[str, Any] = {}
        self._tm: Any | None = None  # SipTransactionManager
        self._thread: Any = None  # threading.Thread running ED2.loop()
        self._uacs: dict[str, Any] = {}  # call_id → sippy UA
        self._known_call: dict[str, Callable[[str, str], None]] = {}  # call_id → on_end cb

    # --- lifecycle -------------------------------------------------------

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the asyncio loop for sippy→asyncio bridging."""
        self._loop = loop

    def start_sippy(self) -> None:
        """Bind the local UDP port and start the sippy event loop thread."""
        import threading

        from sippy.Core.EventDispatcher import ED2
        from sippy.SipLogger import SipLogger
        from sippy.SipTransactionManager import SipTransactionManager

        logger = SipLogger("load-generator-uac")
        self._global_config = {
            "nh_addr": (self.as_address, self.as_port),
            "_sip_address": self.local_address,
            "_sip_port": self.local_port,
            "_sip_uaname": "3rd-party AS POC load generator",
            "_sip_logger": logger,
        }
        self._tm = SipTransactionManager(self._global_config)
        self._global_config["_sip_tm"] = self._tm
        self._thread = threading.Thread(target=ED2.loop, name="gen-sippy-uac", daemon=True)
        self._thread.start()

    def stop_sippy(self) -> None:
        """Release the local UDP port and stop the sippy thread."""
        from sippy.Core.EventDispatcher import ED2

        if self._tm is not None:
            self._tm.shutdown()
            self._tm = None
        ED2.breakLoop()

    # --- send interface (called from asyncio event loop) ----------------

    async def send_invite(
        self,
        *,
        call_id: str,
        call_type: str,
        duration_class: str,
        on_call_ended: Callable[[str, str], None],
    ) -> None:
        """Schedule a real INVITE onto the sippy thread and track lifecycle.

        Args:
            call_id: Generator-side call identifier.
            call_type: One of T1..T6, F1..F4.
            duration_class: One of D1..D4.
            on_call_ended: Called when the call ends with ``(call_id, reason)``.
                This is a plain callable (the CallPool bridge is thread-safe).
        """
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        # Capture sippy objects locally to avoid closure rebinds
        self._send_invite_real(
            call_id, call_type, duration_class, on_call_ended
        )

    # ------------------------------------------------------------------
    # Number selection per call type
    # ------------------------------------------------------------------

    def numbers_for(self, call_type: str) -> tuple[str, str]:
        """Return ``(called, caller)`` for a call type (HLD §12.3)."""
        table: dict[str, tuple[str, str]] = {
            "T1": ("+8613800138000", "1001"),
            "T2": ("02112345678", "1001"),
            "T3": ("0014155551234", "1001"),
            "T4": ("1234", "1001"),
            "T5": ("+8613900139000", "1001"),
            "T6": ("+8613700137000", "1001"),
            "F1": ("+8613800138000", "1001"),
            "F2": ("+8613800138000", "1999"),
            "F3": ("+8613800138000", "1998"),
            "F4": ("+8613800138000", "1001"),
        }
        if call_type not in table:
            raise ValueError(f"Unknown call type: {call_type}")
        return table[call_type]

    # ------------------------------------------------------------------
    # Real sippy UAC send — schedules onto ED2.loop() via sippy.Timeout
    # ------------------------------------------------------------------

    def _send_invite_real(
        self,
        call_id: str,
        call_type: str,
        duration_class: str,
        on_end: Callable[[str, str], None],
    ) -> None:
        """Create UA + send INVITE on the sippy thread.

        Uses :class:`sippy.Time.Timeout.Timeout` which IS sippy's way of
        scheduling callbacks onto ``ED2.loop()`` from any thread.
        """
        from sippy.Time.Timeout import Timeout

        def _on_sippy_thread() -> None:
            self._actually_send(call_id, call_type, duration_class, on_end)

        Timeout(_on_sippy_thread, 0.001, 1)

    def _actually_send(
        self,
        call_id: str,
        call_type: str,
        duration_class: str,
        on_end: Callable[[str, str], None],
    ) -> None:
        """Synchronous sippy UA creation + INVITE send (runs on ED2 thread)."""
        from sippy.CCEvents import CCEventTry
        from sippy.MsgBody import MsgBody
        from sippy.SipAddress import SipAddress
        from sippy.SipConf import SipConf
        from sippy.SipContact import SipContact
        from sippy.SipURL import SipURL
        from sippy.Time.Timeout import Timeout
        from sippy.UA import UA

        if self._tm is None:
            return  # sippy not bound yet

        called, caller = self.numbers_for(call_type)
        self._known_call[call_id] = on_end

        event = CCEventTry(
            (None, caller, called, MsgBody(content=DEFAULT_SDP_OFFER), None, None)
        )
        event.extra_headers = self._isc_headers(caller)

        ua = UA(
            self._global_config,
            self._event_handler(call_id, duration_class),
            nh_address=(self.as_address, self.as_port),
            nh_transport=SipConf.my_transport,
        )
        ua.lContact = SipContact(
            address=SipAddress(
                url=SipURL(
                    host=self.local_address,
                    port=self.local_port,
                    transport=SipConf.my_transport,
                )
            )
        )
        ua.local_ua = str(self._global_config.get("_sip_uaname", ""))
        with _sippy_identity(self._global_config):
            ua.recvEvent(event)
        self._uacs[call_id] = ua

        # D4 — no-answer timer (scheduler on ED2 thread)
        if duration_class == "D4":
            Timeout(
                lambda: self._on_d4_timeout(call_id),
                DurationModel.MIDPOINTS["D4"],
                1,
            )

    # --- ISC headers (mirror s_sbc_mock/uac.py) -------------------------

    def _isc_headers(self, caller: str) -> tuple[Any, ...]:
        """Build ISC-flavoured context headers like the mock S-SBC."""
        from sippy.SipHeader import SipHeader

        return (
            SipHeader(s=f"P-Asserted-Identity: <sip:{caller}@{_IMS_DOMAIN}>"),
            SipHeader(s="Feature-Caps: *;+sip.608"),
            SipHeader(s="Subject: gen-call"),
        )

    # --- sippy event handler (runs on ED2 thread) ----------------------

    def _event_handler(
        self, call_id: str, duration_class: str
    ) -> Callable[[Any, Any], None]:
        """Build the per-call sippy event callback."""

        def handler(event: Any, ua: Any) -> None:
            self._on_sippy_event(event, ua, call_id, duration_class)

        return handler

    def _on_sippy_event(
        self, event: Any, ua: Any, call_id: str, duration_class: str
    ) -> None:
        """Handle one sippy event on the ED2 thread."""
        from sippy.CCEvents import CCEventConnect, CCEventDisconnect, CCEventFail

        if isinstance(event, CCEventConnect):
            # 200 OK — schedule BYE after duration MIDPOINT
            from sippy.Time.Timeout import Timeout

            midpoint = DurationModel.MIDPOINTS[duration_class]
            Timeout(
                lambda: self._send_bye(call_id, "bye"),
                midpoint,
                1,
            )
            return
        if isinstance(event, CCEventDisconnect):
            self._cleanup_call(call_id, "bye")
            return
        if isinstance(event, CCEventFail):
            # AS answered reject (e.g., 4xx/5xx) — tear down, no BYE needed
            self._cleanup_call(call_id, "rejected")
            return

    def _on_d4_timeout(self, call_id: str) -> None:
        """Cancel a D4 call that got no answer within 3 s."""
        ua = self._uacs.pop(call_id, None)
        if ua is not None:
            ua.disconnect()
        self._cleanup_call(call_id, "cancel")

    def force_disconnect_all(self) -> None:
        """Send BYE on every currently-connected call.

        Thread-safe — uses sippy's ``Timeout`` to hop onto the ED2 thread,
        the same pattern as :meth:`_send_invite_real`. Safe to call from
        the asyncio loop thread (which is where CallPool.stop() runs).
        """
        from sippy.Time.Timeout import Timeout

        def _on_sippy_thread() -> None:
            # Snapshot because _send_bye pops from _uacs while iterating
            for call_id in list(self._uacs.keys()):
                self._send_bye(call_id, "pool_stopped")

        Timeout(_on_sippy_thread, 0.001, 1)

    def _send_bye(self, call_id: str, reason: str) -> None:
        """Send BYE on a connected call."""
        ua = self._uacs.pop(call_id, None)
        if ua is not None:
            ua.disconnect()
        self._cleanup_call(call_id, reason)

    def _cleanup_call(self, call_id: str, reason: str) -> None:
        """Notify CallPool the call has ended (thread-safe, called on ED2 thread).

        CallPool's ``_on_call_ended`` callable handles the asyncio→thread bridge
        internally via :func:`asyncio.run_coroutine_threadsafe`, so we just call it.
        """
        on_end = self._known_call.pop(call_id, None)
        self._uacs.pop(call_id, None)
        if on_end is not None:
            on_end(call_id, reason)  # pool handles the bridge

    # --- internal state (instance-level, shared across threads) ---------


# --------------------------------------------------------------------------
# Identity pinning context (mirror tools/s_sbc_mock/uac.py)
# --------------------------------------------------------------------------


@contextmanager
def _sippy_identity(global_config: dict[str, Any]) -> Iterator[None]:
    """Pin the process-wide sippy identity to this UAC while messages generate."""
    from sippy.SipConf import SipConf

    saved = (SipConf.my_address, SipConf.my_port, SipConf.my_uaname)
    SipConf.my_address = str(global_config.get("_sip_address", SipConf.my_address))
    SipConf.my_port = int(global_config.get("_sip_port", SipConf.my_port))
    SipConf.my_uaname = str(global_config.get("_sip_uaname", SipConf.my_uaname))
    try:
        yield
    finally:
        SipConf.my_address, SipConf.my_port, SipConf.my_uaname = saved


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
                if asyncio.iscoroutine(result):
                    result = await result
                return {"status": "started", "detail": result}
            return {"status": "started"}

        @app.post("/load/stop")
        async def stop_load():
            if pool_controller:
                result = pool_controller("stop", None)
                if asyncio.iscoroutine(result):
                    result = await result
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
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if pool_controller:
                result = pool_controller("config", config)
                if asyncio.iscoroutine(result):
                    await result
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


# ======================================================================
# Process entry point
# ======================================================================


async def _amain(args: argparse.Namespace) -> int:
    """Async entry point: sippy thread + CallPool + uvicorn on one loop."""
    import uvicorn

    # 1. Wire up the SIP UAC (starts its own sippy ED2 daemon thread)
    uac = MockSipUac(
        args.as_address, args.as_port,
        local_address=args.local_address, local_port=args.local_port,
    )
    uac.set_loop(asyncio.get_running_loop())
    uac.start_sippy()

    # 2. Build initial pool config
    default_types = frozenset(sorted(CallModel.ALL_TYPES))
    initial_config = PoolConfig(
        args.target_concurrency, args.call_rate, default_types,
    )
    pool = CallPool(initial_config, mock_uac=uac)

    # 3. Async controller bridge — FastAPI endpoints call these through the
    #    pool_controller hook; CallPool.start/stop/set_config are coroutines.
    async def _controller(action: str, config: PoolConfig | None) -> Any:
        if action == "start":
            if not pool.is_running:
                await pool.start()
            return {"pool": pool.snapshot()}
        if action == "stop":
            if pool.is_running:
                await pool.stop()
            return {"pool": pool.snapshot()}
        if action == "config" and config is not None:
            await pool.set_config(config)
            return {"pool": pool.snapshot()}
        return None

    app = build_generator_app(
        pool_state_getter=pool.snapshot,
        pool_controller=_controller,
    )

    # 4. Start uvicorn as a task on this loop
    server_config = uvicorn.Config(
        app, host=args.http_address, port=args.http_port,
        log_level="info", access_log=False,
    )
    server = uvicorn.Server(server_config)
    uvicorn_task = asyncio.create_task(server.serve())

    # 5. Wait for shutdown (uvicorn handles SIGINT/SIGTERM)
    try:
        await uvicorn_task
    finally:
        uac.stop_sippy()
        if pool.is_running:
            await pool.stop()

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — ``python tools/call_load_generator.py [OPTIONS]``."""
    parser = argparse.ArgumentParser(
        description="Call Load Generator — P12 standalone SIP load driver",
    )
    parser.add_argument("--as-address", default="127.0.0.1",
                        help="AS SIP listen address (default 127.0.0.1)")
    parser.add_argument("--as-port", type=int, default=5060,
                        help="AS SIP listen port (default 5060)")
    parser.add_argument("--local-address", default="127.0.0.1",
                        help="Generator local SIP address (default 127.0.0.1)")
    parser.add_argument("--local-port", type=int, default=5099,
                        help="Generator local SIP port (default 5099)")
    parser.add_argument("--http-address", default="127.0.0.1",
                        help="Generator REST/WebSocket HTTP bind address")
    parser.add_argument("--http-port", type=int, default=8765,
                        help="Generator REST/WebSocket HTTP bind port (default 8765)")
    parser.add_argument("--target-concurrency", type=int, default=10,
                        help="Initial pool target concurrency (default 10)")
    parser.add_argument("--call-rate", type=float, default=3.0,
                        help="Initial call rate per second (default 3.0)")
    args = parser.parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
