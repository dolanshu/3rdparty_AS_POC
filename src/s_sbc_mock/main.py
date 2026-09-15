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

"""Mock S-SBC process: UAC (S-CSCF trigger) and UAS (core network) in one process.

Ports are configurable so that tests, CI and several local runs never collide
(``AGENT.md`` section 11). Both sides are driven by the same blocking sippy event loop as
the AS (ADR-0001, ADR-0005): ``ED2`` is a singleton, so one ``ED2.loop()`` serves both
sides and, in the tests, the AS as well.

The two sides need different local ports, and sippy derives the local port from
``_sip_port`` in the global configuration, so each side gets its own configuration and
its own transaction manager.
"""

from __future__ import annotations

import argparse
import logging
import signal
from dataclasses import dataclass, field
from typing import Any

from sippy.Core.EventDispatcher import ED2
from sippy.SipLogger import SipLogger
from sippy.SipTransactionManager import SipTransactionManager
from sippy.Time.Timeout import Timeout

from s_sbc_mock.uac import CallScenario, TrunkUac
from s_sbc_mock.uas import CoreUas

__all__ = ["MockConfig", "SMockApplication", "SIP_USER_AGENT_NAME", "main"]

_LOGGER = logging.getLogger(__name__)

#: User agent name reported by the mock on the trunk.
SIP_USER_AGENT_NAME = "3rd-party AS POC mock S-SBC"

#: Default call the mock places when it runs as a process without a scenario file.
DEFAULT_SCENARIO = CallScenario(
    name="office-to-mobile",
    calling_number="+86216180001",
    called_number="+8613800138000",
)

#: How often the loop looks at the shutdown flag, in seconds.
SHUTDOWN_POLL_SECONDS = 0.1

#: Delay before the first call is placed, in seconds: the AS needs a moment to bind.
FIRST_CALL_DELAY_SECONDS = 0.5


@dataclass
class MockConfig:
    """Runtime parameters of the mock S-SBC.

    Attributes:
        listen_address: Address the UAS side binds.
        listen_port: UDP port the UAS side binds.
        as_address: Address of the AS.
        as_port: UDP port of the AS.
        scenarios: Calls the mock places on startup, one after the other.
        repeat: Place the scenarios again after the last one finished.
    """

    listen_address: str = "127.0.0.1"
    listen_port: int = 15061
    as_address: str = "127.0.0.1"
    as_port: int = 5060
    scenarios: list[CallScenario] = field(default_factory=list)
    repeat: bool = False


class _ShutdownFlag:
    """Shutdown state shared between the signal handlers and the loop."""

    def __init__(self) -> None:
        """Create a flag in the running state."""
        self.requested = False

    def request(self, reason: str) -> None:
        """Request a shutdown.

        Args:
            reason: Short description of the trigger, written to the log.
        """
        self.requested = True
        _LOGGER.info("shutdown requested: %s", reason)


class SMockApplication:
    """Holds the two mock sides and the blocking event loop.

    Attributes:
        config: Runtime parameters.
        uac: UAC side, emulating the S-CSCF trigger.
        uas: UAS side, emulating the core network.
        shutdown: Shutdown state written by the signal handlers.
    """

    def __init__(
        self,
        config: MockConfig,
        *,
        sip_logger: Any | None = None,
        uac_local_port: int | None = None,
    ) -> None:
        """Create the mock application.

        Args:
            config: Runtime parameters.
            sip_logger: SIP message logger shared by both sides; a ``SipLogger`` writing
                to stderr is used when omitted.
            uac_local_port: Local port of the UAC side; ``listen_port - 1`` by default,
                which keeps the compose port matrix valid.
        """
        self.config = config
        self.shutdown = _ShutdownFlag()
        self._sip_logger = sip_logger
        uac_port = uac_local_port if uac_local_port is not None else config.listen_port - 1
        self.uac = TrunkUac(
            config.as_address,
            config.as_port,
            local_address=config.listen_address,
            local_port=uac_port,
        )
        self.uas = CoreUas(
            config.listen_address,
            config.listen_port,
            talk_seconds=config.scenarios[0].talk_seconds if config.scenarios else 0.2,
        )
        self._transaction_managers: list[Any] = []
        self._shutdown_timer: Any = None

    def start(self) -> None:
        """Bind both sides and register their transaction managers.

        Raises:
            OSError: When one of the two UDP ports cannot be bound.
        """
        # ``SipConf`` is a process-wide singleton. The mock deliberately does not write
        # to it: in the tests the AS and the mock share one interpreter, and each side
        # pins its own identity around the messages it generates instead.
        logger = self._sip_logger if self._sip_logger is not None else SipLogger("s-sbc-mock")
        # The core side answers INVITEs, so it needs a request callback; the trunk side
        # only receives responses and the BYE that belongs to a call it already knows
        # about, which sippy routes to the registered consumer of that Call-ID.
        uas_config = self.uas.build_global_config(logger)
        uas_manager = SipTransactionManager(uas_config, self.uas.recv_request)
        uas_config["_sip_tm"] = uas_manager
        uac_config = self.uac.build_global_config(logger)
        uac_manager = SipTransactionManager(uac_config)
        uac_config["_sip_tm"] = uac_manager
        self._transaction_managers = [uas_manager, uac_manager]
        _LOGGER.info(
            "mock S-SBC bound: uas %s:%d, uac %s:%d, next hop %s:%d",
            self.uas.listen_address,
            self.uas.listen_port,
            self.uac.local_address,
            self.uac.local_port,
            self.config.as_address,
            self.config.as_port,
        )

    def run(self) -> int:
        """Run the mock until it is stopped.

        The configured scenarios are placed once the loop is running; the loop stops when
        the process is asked to shut down.

        Returns:
            Process exit code.
        """
        self._shutdown_timer = Timeout(self._poll_shutdown, SHUTDOWN_POLL_SECONDS, -1)
        if self.config.scenarios:
            self.place_scenarios()
        ED2.loop()
        return 0

    def place_scenarios(self, delay_seconds: float = FIRST_CALL_DELAY_SECONDS) -> None:
        """Place the configured scenarios, one after the other.

        Args:
            delay_seconds: Delay before the first call is placed.
        """
        Timeout(self._place_next, delay_seconds, 1, 0)

    def stop(self) -> None:
        """Release both UDP ports and the loop timer."""
        if self._shutdown_timer is not None:
            self._shutdown_timer.cancel()
            self._shutdown_timer = None
        for manager in self._transaction_managers:
            manager.shutdown()
        self._transaction_managers = []

    def _place_next(self, index: int) -> None:
        """Place one scenario and schedule the next one.

        Args:
            index: Position of the scenario in :attr:`MockConfig.scenarios`.
        """
        if self.shutdown.requested or index >= len(self.config.scenarios):
            return
        scenario = self.config.scenarios[index]
        self.uac.place_call(scenario)
        next_index = index + 1
        if next_index < len(self.config.scenarios) or self.config.repeat:
            Timeout(
                self._place_next,
                self._gap_seconds(scenario),
                1,
                next_index % max(len(self.config.scenarios), 1),
            )

    def _gap_seconds(self, scenario: CallScenario) -> float:
        """Return how long to wait before the next scenario is placed.

        Args:
            scenario: The scenario that has just been placed.

        Returns:
            A delay long enough for the call to complete.
        """
        return 1.0 + scenario.ring_seconds + scenario.talk_seconds

    def _poll_shutdown(self) -> None:
        """Stop the loop when a shutdown has been requested."""
        if self.shutdown.requested:
            ED2.breakLoop()


def main(argv: list[str] | None = None) -> int:
    """Run the mock S-SBC process.

    Args:
        argv: Command line arguments; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Mock Service-SBC (trunk side)")
    parser.add_argument("--listen-address", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=15061)
    parser.add_argument(
        "--trunk-port",
        type=int,
        default=None,
        help="UDP port the UAC side sends from; defaults to --listen-port minus one",
    )
    parser.add_argument("--as-address", default="127.0.0.1")
    parser.add_argument("--as-port", type=int, default=5060)
    parser.add_argument(
        "--call",
        action="append",
        default=[],
        metavar="CALLER=CALLED",
        help="place a call on startup, for example +86216180001=+8613800138000",
    )
    parser.add_argument("--repeat", action="store_true", help="place the calls again and again")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    scenarios: list[CallScenario] = []
    for index, call in enumerate(args.call):
        caller, _, called = call.partition("=")
        scenarios.append(
            CallScenario(name=f"cli-{index + 1:02d}", calling_number=caller, called_number=called)
        )
    if not scenarios:
        scenarios.append(DEFAULT_SCENARIO)

    config = MockConfig(
        listen_address=args.listen_address,
        listen_port=args.listen_port,
        as_address=args.as_address,
        as_port=args.as_port,
        scenarios=scenarios,
        repeat=args.repeat,
    )
    app = SMockApplication(config, uac_local_port=args.trunk_port)
    app.start()

    def _handler(signum: int, _frame: Any) -> None:
        app.shutdown.request(signal.Signals(signum).name)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _handler)

    code = app.run()
    app.stop()
    _LOGGER.info("mock S-SBC stopped")
    return code


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
