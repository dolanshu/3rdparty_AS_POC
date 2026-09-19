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

"""Anti-fraud AS process entry point.

A **separate process** (D6, ADR-0007): it owns its own ``SipConf`` identity, its own
``SipTransactionManager``, its own ``ED2.loop()``, its own screening data and its own
internal API. The stack is the same three sippy primitives the first AS uses, in its own
interpreter, so the two AS instances never share a listen port, an event loop or a clock
(``docs/phase2-plan.md`` section 6).

**Every timer this process arms is cancelled from** :meth:`FraudAsStack.stop` **before**
sippy's own ``SipTransactionManager.shutdown()``: that call cancels only its own cache-purge
timer and then drops the tables the per-transaction timers hang from, so anything left armed
fires into a manager whose ``global_config`` is already ``None`` (the P8a lesson,
``docs/phase2-plan.md`` section 3).
"""

from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path
from typing import Any

from sippy.Core.EventDispatcher import ED2
from sippy.SipConf import SipConf
from sippy.SipLogger import SipLogger
from sippy.SipTransactionManager import SipTransactionManager
from sippy.Time.Timeout import Timeout

from anti_fraud_as import __version__
from anti_fraud_as.bootstrap import (
    FraudAsSettings,
    run_startup_self_check,
)
from anti_fraud_as.call_controller import FraudCallMap
from anti_fraud_as.caller_state import CallerStateStore
from anti_fraud_as.internal_api import InternalApiServer
from anti_fraud_as.screening_data import ScreeningDataStore
from as_app.bootstrap import ShutdownController, install_signal_handlers
from as_app.errors import AsError
from as_app.observability.logging import LogDirection, configure_logging, get_logger, log_event
from as_app.observability.metrics import MetricsRegistry, get_metrics_registry
from as_app.observability.tracing import TraceRecorder, get_trace_recorder
from as_app.sip_adapter import cancel_transaction_timers

__all__ = ["FraudAsStack", "main"]

_LOGGER = get_logger(__name__)

#: User agent name reported on the trunk (RFC 3261 section 20.35 ``Server`` header). It is
#: deliberately distinct from the number-translation AS's so a trace shows which instance
#: answered a call.
SIP_USER_AGENT_NAME = "3rd-party AS POC anti-fraud"

#: How often the loop-owned shutdown poller looks at the shutdown flag, in seconds.
SHUTDOWN_POLL_SECONDS = 0.1

#: How often the loop-owned screening-data poller checks the file (ADR-0004 pattern). The
#: reload is pull-based because the sippy thread must not be blocked by file I/O.
SCREENING_RELOAD_POLL_SECONDS = 1.0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line of the anti-fraud AS process.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Anti-fraud Application Server (RFC 8688)")
    parser.add_argument(
        "--self-check-only", action="store_true", help="run the startup self-check and exit"
    )
    parser.add_argument("--log-level", default=None, help="override LOG_LEVEL")
    parser.add_argument(
        "--screening-file", type=Path, default=None, help="override FRAUD_SCREENING_FILE"
    )
    return parser.parse_args(argv)


def _build_sip_logger(settings: FraudAsSettings, sip_logger: Any | None = None) -> Any:
    """Build the sippy SIP message logger for the process.

    The structured application log never carries payloads; this is the separate SIP message
    channel, switched by ``LOG_PAYLOADS`` (``AGENT.md`` section 9).

    Args:
        settings: The loaded configuration.
        sip_logger: An explicit logger, used by the tooling; ``None`` builds the default.

    Returns:
        An object with the ``write()`` interface sippy expects.
    """
    if sip_logger is not None:
        return sip_logger
    logger = SipLogger("anti-fraud-as")
    if not settings.log_payloads:
        logger.write = logger.donoting
    return logger


class FraudAsStack:
    """The sippy signalling stack of the anti-fraud AS process.

    One instance owns the transaction manager, the process-level caller state, the trunk
    call map and the internal API server. It can run the blocking sippy loop
    (:meth:`run`) or be driven step by step, which is how tests would use it.

    Attributes:
        settings: The loaded configuration.
        screening_data: Source of the active block/allow lists and thresholds.
        caller_state: The process-level cross-call state (ADR-0007 decision 8).
        global_config: The sippy global configuration handed to every sippy object.
        call_map: Trunk entry point: peer allowlist and one controller per call.
        transaction_manager: The sippy transaction manager of the process.
        internal_api: Health and counters endpoint; ``None`` when it is not started.
        metrics: Counter registry.
        tracer: Per-Call-ID trace recorder.
    """

    def __init__(
        self,
        settings: FraudAsSettings,
        *,
        screening_data: ScreeningDataStore | None = None,
        caller_state: CallerStateStore | None = None,
        metrics: MetricsRegistry | None = None,
        tracer: TraceRecorder | None = None,
        sip_logger: Any | None = None,
    ) -> None:
        """Create the signalling stack without binding anything yet.

        Args:
            settings: The loaded configuration.
            screening_data: Screening-data holder; one is created from ``settings`` when
                omitted.
            caller_state: Cross-call state; one is created from the screening data when
                omitted.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            sip_logger: Explicit sippy SIP message logger, used by the tooling.
        """
        self.settings = settings
        self.screening_data = screening_data or ScreeningDataStore(settings.fraud_screening_file)
        self.caller_state = caller_state or CallerStateStore(self.screening_data.current.policy)
        self.metrics = metrics or get_metrics_registry()
        self.tracer = tracer or get_trace_recorder()
        self.internal_api: InternalApiServer | None = None
        self._sip_logger = _build_sip_logger(settings, sip_logger)
        self._shutdown_timer: Any = None
        self._reload_timer: Any = None
        self.transaction_manager: Any = None
        self.global_config: dict[str, Any] = {}
        self.call_map: FraudCallMap | None = None

    def start(self) -> None:
        """Bind the trunk socket, the transaction manager and the call map.

        Raises:
            AsError: Propagated from sippy when the signalling port cannot be bound.
        """
        settings = self.settings
        SipConf.my_uaname = SIP_USER_AGENT_NAME
        SipConf.my_address = settings.fraud_sip_listen_address
        SipConf.my_port = settings.fraud_sip_listen_port
        self.global_config = {
            "nh_addr": (settings.fraud_sbc_peer_address, settings.fraud_sbc_peer_port),
            "_sip_address": settings.fraud_sip_listen_address,
            "_sip_port": settings.fraud_sip_listen_port,
            "_sip_uaname": SIP_USER_AGENT_NAME,
            "_sip_logger": self._sip_logger,
        }
        self.call_map = FraudCallMap(
            self.global_config,
            self.screening_data,
            self.caller_state,
            allowed_peers=tuple(settings.fraud_allowed_peers),
            metrics=self.metrics,
            tracer=self.tracer,
        )
        self.transaction_manager = SipTransactionManager(
            self.global_config, self.call_map.recv_request
        )
        self.global_config["_sip_tm"] = self.transaction_manager
        log_event(
            _LOGGER,
            logging.INFO,
            "anti-fraud signalling stack bound",
            direction=LogDirection.INTERNAL,
            listen=f"{settings.fraud_sip_listen_address}:{settings.fraud_sip_listen_port}",
            next_hop=f"{settings.fraud_sbc_peer_address}:{settings.fraud_sbc_peer_port}",
            allowed_peers=",".join(settings.fraud_allowed_peers),
        )

    def start_internal_api(self) -> InternalApiServer:
        """Start the health and counters endpoint on its own thread.

        Returns:
            The running internal API server.
        """
        server = InternalApiServer(
            self.settings.fraud_internal_api_address,
            self.settings.fraud_internal_api_port,
            version=__version__,
            screening_data_store=self.screening_data,
            metrics=self.metrics,
            tracer=self.tracer,
        )
        server.start()
        self.internal_api = server
        log_event(
            _LOGGER,
            logging.INFO,
            "internal api listening",
            direction=LogDirection.INTERNAL,
            address=(
                f"{self.settings.fraud_internal_api_address}:"
                f"{self.settings.fraud_internal_api_port}"
            ),
        )
        return server

    def run(self, shutdown: ShutdownController) -> None:
        """Run the blocking sippy event loop until a shutdown is requested.

        Signal handlers only set the flag; the timers below are owned by the loop, which is
        the only place allowed to stop it (ADR-0002, ``AGENT.md`` section 6). The second
        loop-owned timer polls the screening-data file for hot reload: the reload is
        pull-based because the sippy thread must not be blocked by file I/O.

        Args:
            shutdown: Shutdown state written by the signal handlers.
        """
        self._shutdown_timer = Timeout(self._poll_shutdown, SHUTDOWN_POLL_SECONDS, -1, shutdown)
        self._reload_timer = Timeout(self._poll_screening_reload, SCREENING_RELOAD_POLL_SECONDS, -1)
        log_event(
            _LOGGER,
            logging.INFO,
            "sippy event loop running",
            direction=LogDirection.INTERNAL,
            screening_file=str(self.settings.fraud_screening_file),
            reload_poll_seconds=str(SCREENING_RELOAD_POLL_SECONDS),
        )
        ED2.loop()

    def stop(self) -> None:
        """Release the trunk socket, the loop timers and the internal API port.

        Everything the stack armed is cancelled before sippy's own
        ``SipTransactionManager.shutdown()`` runs: that call only cancels its own cache-purge
        timer and releases the sockets, so a timer armed here would fire into a torn-down
        stack (the P8a lesson, see :func:`as_app.sip_adapter.cancel_transaction_timers`).
        """
        if self._shutdown_timer is not None:
            self._shutdown_timer.cancel()
            self._shutdown_timer = None
        if self._reload_timer is not None:
            self._reload_timer.cancel()
            self._reload_timer = None
        if self.call_map is not None:
            self.call_map.dispose()
        if self.transaction_manager is not None:
            cancel_transaction_timers(self.transaction_manager)
            self.transaction_manager.shutdown()
            self.transaction_manager = None
        if self.internal_api is not None:
            self.internal_api.stop()
            self.internal_api = None

    @staticmethod
    def _poll_shutdown(shutdown: ShutdownController) -> None:
        """Stop the sippy loop when a shutdown has been requested.

        Args:
            shutdown: Shutdown state written by the signal handlers.
        """
        if shutdown.requested:
            ED2.breakLoop()

    def _poll_screening_reload(self) -> None:
        """Reload the screening data when the file changed on disk.

        Reload is fail-safe: a broken edit keeps the previous document active and logs the
        error (``AS-FRAUD-005``). A successful reload re-applies the window and reputation
        parameters to the process-level state, so an operator change takes effect without a
        restart.
        """
        try:
            if self.screening_data.maybe_reload():
                data = self.screening_data.current
                self.caller_state.reconfigure(data.policy)
                log_event(
                    _LOGGER,
                    logging.INFO,
                    "screening data reloaded",
                    direction=LogDirection.INTERNAL,
                    data_set=data.document.name,
                    block_list=str(len(data.document.block_list)),
                    allow_list=str(len(data.document.allow_list)),
                    window_seconds=str(data.document.window.seconds),
                    screening_file=str(self.settings.fraud_screening_file),
                )
        except AsError as error:
            log_event(
                _LOGGER,
                logging.ERROR,
                "screening data reload failed; previous data stays active",
                direction=LogDirection.INTERNAL,
                screening_file=str(self.settings.fraud_screening_file),
                **error.as_log_fields(),
            )


def main(argv: list[str] | None = None) -> int:
    """Run the anti-fraud AS process.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` on a clean shutdown, ``1`` when the configuration or the
        screening data is invalid.
    """
    args = _parse_args(argv)
    settings = FraudAsSettings()
    if args.log_level:
        settings = settings.model_copy(update={"log_level": args.log_level})
    if args.screening_file:
        settings = settings.model_copy(update={"fraud_screening_file": args.screening_file})

    configure_logging(settings.log_level, structured=settings.log_structured)
    controller = ShutdownController()
    install_signal_handlers(controller)

    log_event(
        _LOGGER,
        logging.INFO,
        "anti-fraud application server starting",
        direction=LogDirection.INTERNAL,
        version=__version__,
        listen=f"{settings.fraud_sip_listen_address}:{settings.fraud_sip_listen_port}",
        next_hop=f"{settings.fraud_sbc_peer_address}:{settings.fraud_sbc_peer_port}",
    )
    try:
        run_startup_self_check(settings)
    except AsError as error:
        log_event(
            _LOGGER,
            logging.ERROR,
            "startup self-check failed",
            direction=LogDirection.INTERNAL,
            **error.as_log_fields(),
        )
        return 1

    log_event(
        _LOGGER,
        logging.INFO,
        "startup self-check passed",
        direction=LogDirection.INTERNAL,
        screening_file=str(settings.fraud_screening_file),
    )
    if args.self_check_only:
        return 0

    stack = FraudAsStack(settings)
    log_event(
        _LOGGER,
        logging.INFO,
        "screening data active",
        direction=LogDirection.INTERNAL,
        data_set=stack.screening_data.current.document.name,
        block_list=str(len(stack.screening_data.current.document.block_list)),
        allow_list=str(len(stack.screening_data.current.document.allow_list)),
    )
    stack.start()
    stack.start_internal_api()
    stack.run(controller)
    stack.stop()
    log_event(
        _LOGGER,
        logging.INFO,
        "shutdown complete",
        direction=LogDirection.INTERNAL,
        reason=controller.reason or signal.Signals.SIGTERM.name,
        grace_seconds=str(settings.shutdown_grace_seconds),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
