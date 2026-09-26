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

"""Multi-process chained IMS runtime — orchestrator without in-process AS (P14)."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from dataclasses import asdict
from typing import Any

from sippy.Core.EventDispatcher import ED2

from ims_mock.chained_stack import ChainedImsStack, ExternalRuntimePorts

__all__ = ["ExternalChainedRuntime", "main"]

_LOGGER = logging.getLogger(__name__)


class ExternalChainedRuntime:
    """Runs S-SBC passthrough, orchestrator, P-CSCF and UAS for external AS processes."""

    def __init__(self, stack: ChainedImsStack, ports: ExternalRuntimePorts) -> None:
        """Attach to a started :class:`ChainedImsStack` and its port map."""
        self.stack = stack
        self.ports = ports
        self._thread: threading.Thread | None = None
        self._stopping = False

    @classmethod
    def from_ports(
        cls, ports: ExternalRuntimePorts, bind_address: str = "127.0.0.1"
    ) -> ExternalChainedRuntime:
        """Build and start the mock side of a chained topology.

        Args:
            ports: External AS and mock UDP ports.
            bind_address: Address every component binds on.

        Returns:
            A started runtime whose :meth:`run` drives ``ED2.loop()``.
        """
        stack = ChainedImsStack.build_external(
            as1_port=ports.as1_port,
            as2_port=ports.as2_port,
            return_port=ports.return_port,
            forward_port=ports.forward_port,
            terminating_port=ports.terminating_port,
            pcscf_port=ports.pcscf_port,
            bind_address=bind_address,
        )
        stack.start()
        return cls(stack, ports)

    def run(self) -> None:
        """Block on the sippy event loop until :meth:`stop` is called."""
        _LOGGER.info(
            "external chained runtime listening return=%s forward=%s term=%s",
            self.ports.return_port,
            self.ports.forward_port,
            self.ports.terminating_port,
        )
        ED2.loop()

    def run_background(self) -> None:
        """Start :meth:`run` on a daemon thread."""
        self._thread = threading.Thread(target=self.run, name="ims-external-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Tear down the stack and stop the event loop."""
        if self._stopping:
            return
        self._stopping = True
        self.stack.stop()
        ED2.breakLoop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def ports_dict(self) -> dict[str, Any]:
        """Return port map for shell scripts and supervisors."""
        data = asdict(self.ports)
        data["ingress_port"] = self.ports.ingress_port
        return data


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P14 external iFC chained IMS runtime")
    parser.add_argument("--bind-address", default="127.0.0.1")
    parser.add_argument("--as1-port", type=int, required=True, help="Anti-fraud AS SIP port")
    parser.add_argument("--as2-port", type=int, required=True, help="Translation AS SIP port")
    parser.add_argument("--return-port", type=int, required=True, help="S-SBC return port")
    parser.add_argument(
        "--forward-port", type=int, required=True, help="Orchestrator UAC bind port"
    )
    parser.add_argument("--terminating-port", type=int, required=True, help="Terminating UAS port")
    parser.add_argument("--pcscf-port", type=int, required=True, help="P-CSCF relay port")
    parser.add_argument(
        "--print-ports",
        action="store_true",
        help="Emit one JSON line of ports on stdout before blocking",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``python -m ims_mock.external_runtime``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    ports = ExternalRuntimePorts(
        as1_port=args.as1_port,
        as2_port=args.as2_port,
        return_port=args.return_port,
        forward_port=args.forward_port,
        terminating_port=args.terminating_port,
        pcscf_port=args.pcscf_port,
    )
    runtime = ExternalChainedRuntime.from_ports(ports, bind_address=args.bind_address)
    if args.print_ports:
        print(json.dumps(runtime.ports_dict()), flush=True)

    def _shutdown(_signum: int, _frame: Any) -> None:
        runtime.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    runtime.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
