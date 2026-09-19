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
:mod:`as_app.call_controller` behind it. The process skeleton is shared with the anti-fraud
AS and lives in the platform library (``as_platform.main.BaseAsStack``); this module keeps
the number-translation identity — its user agent name, its rule set and its reload timer —
as a subclass (ADR-0009 decision 2). M1 wired the transaction manager, the trunk call map
and the graceful shutdown of the loop; the behaviour of the stack was verified with
``tools/sippy_probe.py`` and is re-verified by the e2e suite.

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

from as_platform.main import BaseAsStack

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
from as_app.observability.metrics import MetricsRegistry
from as_app.observability.tracing import TraceRecorder
from as_app.routing.rules import RuleSetStore

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


class AsStack(BaseAsStack[AsSettings]):
    """The sippy signalling stack of the number-translation AS process.

    The sippy process skeleton — the transaction manager, the trunk call map, the internal
    API server and the graceful shutdown of the loop — is inherited from
    :class:`as_platform.main.BaseAsStack`; this subclass supplies the number-translation
    identity and the rule set the call controller needs (ADR-0009 decision 2). It can run
    the blocking sippy loop or be driven step by step, which is how the integration and e2e
    tests use it.

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

    sip_user_agent_name = SIP_USER_AGENT_NAME
    sip_logger_name = "as"
    shutdown_poll_seconds = SHUTDOWN_POLL_SECONDS
    reload_poll_seconds = RULE_RELOAD_POLL_SECONDS

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
        self.rule_set_store = rule_set_store or RuleSetStore(settings.rules_file)
        super().__init__(
            settings,
            sip_address=settings.sip_listen_address,
            sip_port=settings.sip_listen_port,
            peer_address=settings.sbc_peer_address,
            peer_port=settings.sbc_peer_port,
            allowed_peers=tuple(settings.allowed_peers),
            api_address=settings.internal_api_address,
            api_port=settings.internal_api_port,
            metrics=metrics,
            tracer=tracer,
            sip_logger=sip_logger,
        )

    def _create_call_map(self, global_config: dict[str, Any]) -> TrunkCallMap:
        """Create the number-translation trunk call map.

        Args:
            global_config: sippy global configuration; ``nh_addr`` carries the next hop.

        Returns:
            The trunk call map wired to this AS's rule set.
        """
        return TrunkCallMap(
            global_config,
            self.rule_set_store,
            allowed_peers=tuple(self.settings.allowed_peers),
            metrics=self.metrics,
            tracer=self.tracer,
        )

    def _create_internal_api_server(self, address: str, port: int) -> InternalApiServer:
        """Create the number-translation internal API server.

        Args:
            address: Local address the server binds.
            port: Local TCP port the server binds.

        Returns:
            The internal API server bound to this AS's rule set.
        """
        return InternalApiServer(
            address,
            port,
            version=__version__,
            rule_set_store=self.rule_set_store,
            metrics=self.metrics,
            tracer=self.tracer,
        )

    def _poll_reload(self) -> None:
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

    def _reload_log_fields(self) -> dict[str, str]:
        """Return the reload-source log field for the event loop start line.

        Returns:
            The rules-file field naming the reloaded file.
        """
        return {"rules_file": str(self.settings.rules_file)}


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
