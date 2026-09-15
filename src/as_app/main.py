# Copyright 2026 the 3rd-party AS POC authors.
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

The full stack is ``SipConf`` + ``SipTransactionManager`` + ``ED2.loop()``
(``AGENT.md`` section 5). M0 delivers everything up to the point where the loop would
start: configuration, logging, the startup self-check, the rule set and graceful
shutdown. The sippy transaction manager and the call control hook are wired in M1; the
behaviour of that stack was verified with ``tools/sippy_probe.py`` (see
``docs/acceptance/report.md``).
"""

from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path

from as_app import __version__
from as_app.bootstrap import (
    AsSettings,
    ShutdownController,
    install_signal_handlers,
    run_startup_self_check,
)
from as_app.errors import AsError
from as_app.observability.logging import LogDirection, configure_logging, get_logger, log_event
from as_app.routing.rules import RuleSetStore

__all__ = ["main"]

_LOGGER = get_logger(__name__)


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


def _wait_for_shutdown(controller: ShutdownController) -> None:
    """Block until a shutdown signal arrives.

    Signal handlers only request shutdown (see :mod:`as_app.bootstrap`); the loop below
    owns the decision to stop, which is the same pattern the sippy event loop will use in
    M1 because ``ED2.loop()`` cannot be interrupted from a handler.

    Args:
        controller: Shutdown state written by the signal handlers.
    """
    while not controller.requested:
        signal.pause()


def main(argv: list[str] | None = None) -> int:
    """Run the AS process.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` on a clean shutdown, ``1`` when the configuration or the
        rule set is invalid.
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
    log_event(
        _LOGGER,
        logging.WARNING,
        "sippy transaction manager is wired in M1; the process is idle until then",
        direction=LogDirection.INTERNAL,
    )
    _wait_for_shutdown(controller)
    log_event(
        _LOGGER,
        logging.INFO,
        "shutdown complete",
        direction=LogDirection.INTERNAL,
        reason=controller.reason or "unknown",
        grace_seconds=str(settings.shutdown_grace_seconds),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
