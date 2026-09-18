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

"""AS process entry point.

The stack is ``SipConf`` + ``SipTransactionManager`` + ``ED2.loop()``
(``AGENT.md`` section 5), with the call control logic of
:mod:`as_app.call_controller` behind it. M1 wires the transaction manager, the trunk
call map and the graceful shutdown of the loop; the behaviour of the stack was verified
with ``tools/sippy_probe.py`` and is re-verified by the e2e suite.

Two sippy facts shape this module (see ``docs/operations/troubleshooting.md``):

- ``ED2.loop()`` blocks and must run on the main thread, so shutdown is a loop-owned
  timer that only *observes* the flag the signal handlers set.
- ``global_config['_sip_logger']`` must be a ``SipLogger``; ``None`` raises on the first
  inbound message.

The mock S-SBC is never imported here: pointing the AS at a real S-SBC is a
configuration change only (``AGENT.md`` section 8).
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

from as_app import __version__
from as_app.bootstrap import (
    AsSettings,
    ShutdownController,
    install_signal_handlers,
    run_startup_self_check,
)
from as_app.call_controller import TrunkCallMap
from as_app.errors import AsError
from as_app.internal_api import InternalApiServer
from as_app.observability.logging import LogDirection, configure_logging, get_logger, log_event
from as_app.observability.metrics import MetricsRegistry, get_metrics_registry
from as_app.observability.tracing import TraceRecorder, get_trace_recorder
from as_app.routing.rules import RuleSetStore
from as_app.sip_adapter import cancel_transaction_timers

__all__ = ["AsStack", "main"]

_LOGGER = get_logger(__name__)

#: User agent name reported on the trunk (RFC 3261 section 20.35 ``Server`` header).
SIP_USER_AGENT_NAME = "3rd-party AS POC"

#: How often the loop-owned shutdown poller looks at the shutdown flag, in seconds.
SHUTDOWN_POLL_SECONDS = 0.1

#: How often the loop-owned rule reload poller checks the rules file (ADR-0004). The
#: reload is pull-based because the sippy thread must not be blocked by file I/O.
RULE_RELOAD_POLL_SECONDS = 1.0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line of the AS process.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Third-party Application Server (B2BUA)")
    parser.add_argument(
        "--self-check-only", action="store_true", help="run the startup self-check and exit"
    )
    parser.add_argument("--log-level", default=None, help="override LOG_LEVEL")
    parser.add_argument("--rules-file", type=Path, default=None, help="override RULES_FILE")
    return parser.parse_args(argv)


def _build_sip_logger(settings: AsSettings, sip_logger: Any | None = None) -> Any:
    """Build the sippy SIP message logger for the process.

    The structured application log never carries payloads. This is the separate SIP
    message channel, and it is switched by ``LOG_PAYLOADS`` (``AGENT.md`` section 9):
    when payload logging is off, sippy's message log is suppressed instead of printed.

    Args:
        settings: The loaded configuration.
        sip_logger: An explicit logger, used by the capture tooling; ``None`` builds the
            default one.

    Returns:
        An object with the ``write()`` interface sippy expects.
    """
    if sip_logger is not None:
        return sip_logger
    logger = SipLogger("as")
    if not settings.log_payloads:
        logger.write = logger.donoting
    return logger


class AsStack:
    """The sippy signalling stack of the AS process.

    One instance owns the transaction manager, the trunk call map and the internal API
    server. It can run the blocking sippy loop (:meth:`run`) or be driven step by step,
    which is how the integration and e2e tests use it.

    Attributes:
        settings: The loaded configuration.
        global_config: The sippy global configuration handed to every sippy object.
        rule_set_store: Source of the currently active rule set.
        call_map: Trunk entry point: peer allowlist and one controller per call.
        transaction_manager: The sippy transaction manager of the process.
        internal_api: Health and counters endpoint; ``None`` when it is not started.
        metrics: Counter registry.
        tracer: Per-Call-ID trace recorder.
    """

    def __init__(
        self,
        settings: AsSettings,
        *,
        rule_set_store: RuleSetStore | None = None,
        metrics: MetricsRegistry | None = None,
        tracer: TraceRecorder | None = None,
        sip_logger: Any | None = None,
    ) -> None:
        """Create the signalling stack without binding anything yet.

        Args:
            settings: The loaded configuration.
            rule_set_store: Rule set holder; one is created from ``settings`` when omitted.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            sip_logger: Explicit sippy SIP message logger, used by the capture tooling.
        """
        self.settings = settings
        self.rule_set_store = rule_set_store or RuleSetStore(settings.rules_file)
        self.metrics = metrics or get_metrics_registry()
        self.tracer = tracer or get_trace_recorder()
        self.internal_api: InternalApiServer | None = None
        self._sip_logger = _build_sip_logger(settings, sip_logger)
        self._shutdown_timer: Any = None
        self._reload_timer: Any = None
        self.transaction_manager: Any = None
        self.global_config: dict[str, Any] = {}
        self.call_map: TrunkCallMap | None = None

    def start(self) -> None:
        """Bind the trunk socket, the transaction manager and the internal API.

        Raises:
            AsError: Propagated from sippy when the signalling port cannot be bound.
        """
        settings = self.settings
        SipConf.my_uaname = SIP_USER_AGENT_NAME
        SipConf.my_address = settings.sip_listen_address
        SipConf.my_port = settings.sip_listen_port
        self.global_config = {
            "nh_addr": (settings.sbc_peer_address, settings.sbc_peer_port),
            "_sip_address": settings.sip_listen_address,
            "_sip_port": settings.sip_listen_port,
            "_sip_uaname": SIP_USER_AGENT_NAME,
            "_sip_logger": self._sip_logger,
        }
        self.call_map = TrunkCallMap(
            self.global_config,
            self.rule_set_store,
            allowed_peers=tuple(settings.allowed_peers),
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
            "signalling stack bound",
            direction=LogDirection.INTERNAL,
            listen=f"{settings.sip_listen_address}:{settings.sip_listen_port}",
            next_hop=f"{settings.sbc_peer_address}:{settings.sbc_peer_port}",
            allowed_peers=",".join(settings.allowed_peers),
        )

    def start_internal_api(self) -> InternalApiServer:
        """Start the health and counters endpoint on its own thread.

        Returns:
            The running internal API server.
        """
        server = InternalApiServer(
            self.settings.internal_api_address,
            self.settings.internal_api_port,
            version=__version__,
            rule_set_store=self.rule_set_store,
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
            address=f"{self.settings.internal_api_address}:{self.settings.internal_api_port}",
        )
        return server

    def run(self, shutdown: ShutdownController) -> None:
        """Run the blocking sippy event loop until a shutdown is requested.

        Signal handlers only set the flag; the timer below is owned by the loop, which is
        the only place allowed to stop it (ADR-0002, ``AGENT.md`` section 6). A second
        loop-owned timer polls the rules file for hot reload (ADR-0004): the reload is
        pull-based because the sippy thread must not be blocked by file I/O.

        Args:
            shutdown: Shutdown state written by the signal handlers.
        """
        self._shutdown_timer = Timeout(self._poll_shutdown, SHUTDOWN_POLL_SECONDS, -1, shutdown)
        self._reload_timer = Timeout(self._poll_rule_reload, RULE_RELOAD_POLL_SECONDS, -1)
        log_event(
            _LOGGER,
            logging.INFO,
            "sippy event loop running",
            direction=LogDirection.INTERNAL,
            rules_file=str(self.settings.rules_file),
            reload_poll_seconds=str(RULE_RELOAD_POLL_SECONDS),
        )
        ED2.loop()

    def stop(self) -> None:
        """Release the trunk socket, the loop timers and the internal API port.

        Everything the stack armed has to be cancelled before sippy's own
        :meth:`SipTransactionManager.shutdown` runs: that call only cancels its own
        cache-purge timer and releases the sockets, so the loop-owned timers of calls
        that are still in flight would survive it and fire into a torn-down stack. See
        :func:`as_app.sip_adapter.cancel_transaction_timers` and the gap row "Closing a
        transaction manager mid-retransmission" in ``docs/production-gaps.md``.
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

    def _poll_rule_reload(self) -> None:
        """Reload the rule set when the file changed on disk (ADR-0004).

        Reload is fail-safe: a broken edit keeps the previous rule set active and logs
        the error. A successful reload logs the new rule set name and rule count so the
        operator can see that the change took effect.
        """
        try:
            if self.rule_set_store.maybe_reload():
                rule_set = self.rule_set_store.current
                log_event(
                    _LOGGER,
                    logging.INFO,
                    "rule set reloaded",
                    direction=LogDirection.INTERNAL,
                    rule_set=rule_set.document.name,
                    rules=str(len(rule_set.ordered_rules)),
                    next_hops=str(len(rule_set.document.next_hops)),
                    rules_file=str(self.settings.rules_file),
                )
        except AsError as error:
            log_event(
                _LOGGER,
                logging.ERROR,
                "rule set reload failed; previous rule set stays active",
                direction=LogDirection.INTERNAL,
                rules_file=str(self.settings.rules_file),
                **error.as_log_fields(),
            )


def main(argv: list[str] | None = None) -> int:
    """Run the AS process.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` on a clean shutdown, ``1`` when the configuration or the
        rule set is invalid.

    Raises:
        SystemExit: Never raised here; the exit code is returned for ``sys.exit``.
    """
    args = _parse_args(argv)
    settings = AsSettings()
    if args.log_level:
        settings = settings.model_copy(update={"log_level": args.log_level})
    if args.rules_file:
        settings = settings.model_copy(update={"rules_file": args.rules_file})

    configure_logging(settings.log_level, structured=settings.log_structured)
    controller = ShutdownController()
    install_signal_handlers(controller)

    log_event(
        _LOGGER,
        logging.INFO,
        "application server starting",
        direction=LogDirection.INTERNAL,
        version=__version__,
        listen=f"{settings.sip_listen_address}:{settings.sip_listen_port}",
        next_hop=f"{settings.sbc_peer_address}:{settings.sbc_peer_port}",
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
        rules_file=str(settings.rules_file),
    )
    if args.self_check_only:
        return 0

    store = RuleSetStore(settings.rules_file)
    log_event(
        _LOGGER,
        logging.INFO,
        "rule set active",
        direction=LogDirection.INTERNAL,
        rule_set=store.current.document.name,
        rules=str(len(store.current.ordered_rules)),
        next_hops=str(len(store.current.document.next_hops)),
    )
    stack = AsStack(settings, rule_set_store=store)
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
