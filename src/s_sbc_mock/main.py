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
the AS (ADR-0001).

The call behaviour is wired in M1; M0 delivers the process, the parameters and the
scenario catalogue.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from s_sbc_mock.uac import CallScenario, TrunkUac
from s_sbc_mock.uas import CoreUas

__all__ = ["MockConfig", "SMockApplication", "main"]


@dataclass
class MockConfig:
    """Runtime parameters of the mock S-SBC.

    Attributes:
        listen_address: Address the UAS side binds.
        listen_port: UDP port the UAS side binds.
        as_address: Address of the AS.
        as_port: UDP port of the AS.
        scenarios: Calls the mock can place.
    """

    listen_address: str = "127.0.0.1"
    listen_port: int = 15061
    as_address: str = "127.0.0.1"
    as_port: int = 5060
    scenarios: list[CallScenario] = field(default_factory=list)


class SMockApplication:
    """Holds the two mock sides and the blocking event loop.

    Attributes:
        config: Runtime parameters.
        uac: UAC side, emulating the S-CSCF trigger.
        uas: UAS side, emulating the core network.
    """

    def __init__(self, config: MockConfig) -> None:
        """Create the mock application.

        Args:
            config: Runtime parameters.
        """
        self.config = config
        self.uac = TrunkUac(
            config.as_address,
            config.as_port,
            local_address=config.listen_address,
            local_port=config.listen_port - 1,
        )
        self.uas = CoreUas(config.listen_address, config.listen_port)

    def run(self) -> int:
        """Run the mock until it is stopped.

        Returns:
            Process exit code.

        Raises:
            NotImplementedError: Until the sippy event loop is wired in M1.
        """
        raise NotImplementedError("SMockApplication.run() is implemented in M1 (signalling path)")


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
    parser.add_argument("--as-address", default="127.0.0.1")
    parser.add_argument("--as-port", type=int, default=5060)
    args = parser.parse_args(argv)

    config = MockConfig(
        listen_address=args.listen_address,
        listen_port=args.listen_port,
        as_address=args.as_address,
        as_port=args.as_port,
    )
    return SMockApplication(config).run()


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
