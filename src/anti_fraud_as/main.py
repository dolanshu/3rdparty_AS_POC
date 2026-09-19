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
internal API. The process skeleton is shared with the number-translation AS and lives in the
platform library (``as_platform.main.BaseAsStack``); this module keeps the anti-fraud
identity — its user agent name, its screening data and its reload timer — as a subclass
(ADR-0009 decision 2), so the two AS instances never share a listen port, an event loop or a
clock (``docs/phase2-plan.md`` section 6).

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

from as_platform.bootstrap import ShutdownController, install_signal_handlers
from as_platform.errors import AsError
from as_platform.main import BaseAsStack
from as_platform.observability.logging import (
    LogDirection,
    configure_logging,
    get_logger,
    log_event,
)
from as_platform.observability.metrics import MetricsRegistry
from as_platform.observability.tracing import TraceRecorder

from anti_fraud_as import __version__
from anti_fraud_as.bootstrap import (
    FraudAsSettings,
    run_startup_self_check,
)
from anti_fraud_as.call_controller import FraudCallMap
from anti_fraud_as.caller_state import CallerStateStore
from anti_fraud_as.internal_api import InternalApiServer
from anti_fraud_as.screening_data import ScreeningDataStore

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


class FraudAsStack(BaseAsStack[FraudAsSettings]):
    """The sippy signalling stack of the anti-fraud AS process.

    The sippy process skeleton — the transaction manager, the trunk call map, the internal
    API server and the graceful shutdown of the loop — is inherited from
    :class:`as_platform.main.BaseAsStack`; this subclass supplies the anti-fraud identity,
    the process-level caller state and the screening data the call controller needs
    (ADR-0009 decision 2). It can run the blocking sippy loop or be driven step by step.

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

    sip_user_agent_name = SIP_USER_AGENT_NAME
    sip_logger_name = "anti-fraud-as"
    bound_log_message = "anti-fraud signalling stack bound"
    shutdown_poll_seconds = SHUTDOWN_POLL_SECONDS
    reload_poll_seconds = SCREENING_RELOAD_POLL_SECONDS

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
        self.screening_data = screening_data or ScreeningDataStore(settings.fraud_screening_file)
        self.caller_state = caller_state or CallerStateStore(self.screening_data.current.policy)
        super().__init__(
            settings,
            sip_address=settings.fraud_sip_listen_address,
            sip_port=settings.fraud_sip_listen_port,
            peer_address=settings.fraud_sbc_peer_address,
            peer_port=settings.fraud_sbc_peer_port,
            allowed_peers=tuple(settings.fraud_allowed_peers),
            api_address=settings.fraud_internal_api_address,
            api_port=settings.fraud_internal_api_port,
            metrics=metrics,
            tracer=tracer,
            sip_logger=sip_logger,
        )

    def _create_call_map(self, global_config: dict[str, Any]) -> FraudCallMap:
        """Create the anti-fraud trunk call map.

        Args:
            global_config: sippy global configuration; ``nh_addr`` carries the next hop.

        Returns:
            The trunk call map wired to this AS's screening data and caller state.
        """
        return FraudCallMap(
            global_config,
            self.screening_data,
            self.caller_state,
            allowed_peers=tuple(self.settings.fraud_allowed_peers),
            metrics=self.metrics,
            tracer=self.tracer,
        )

    def _create_internal_api_server(self, address: str, port: int) -> InternalApiServer:
        """Create the anti-fraud internal API server.

        Args:
            address: Local address the server binds.
            port: Local TCP port the server binds.

        Returns:
            The internal API server bound to this AS's screening data.
        """
        return InternalApiServer(
            address,
            port,
            version=__version__,
            screening_data_store=self.screening_data,
            metrics=self.metrics,
            tracer=self.tracer,
        )

    def _poll_reload(self) -> None:
        """Run the loop-owned screening-data reload.

        The base schedules this hook as the reload timer; the callback keeps its historical
        name, :meth:`_poll_screening_reload`, because the integration tests drive it
        directly (``tests/integration/test_fraud_screening_path.py``).
        """
        self._poll_screening_reload()

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
            # The screening-data errors carry ``screening_file`` in their context, so the
            # field is merged into one mapping instead of being supplied twice: the error
            # handler runs inside the loop-owned reload timer, so it must not raise — the
            # whole point of this fail-safe path is to contain a broken edit.
            fields = {"screening_file": str(self.settings.fraud_screening_file)}
            fields.update(error.as_log_fields())
            log_event(
                _LOGGER,
                logging.ERROR,
                "screening data reload failed; previous data stays active",
                direction=LogDirection.INTERNAL,
                **fields,
            )

    def _reload_log_fields(self) -> dict[str, str]:
        """Return the reload-source log field for the event loop start line.

        Returns:
            The screening-file field naming the reloaded file.
        """
        return {"screening_file": str(self.settings.fraud_screening_file)}


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
