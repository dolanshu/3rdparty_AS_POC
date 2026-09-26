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

"""Allocate ports for Phase 3 chained demo and print JSON for shell scripts (P14)."""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def allocate_chained_ports(
    *,
    as1_port: int | None,
    as2_port: int | None,
    return_port: int | None,
    forward_port: int | None,
    terminating_port: int | None,
    pcscf_port: int | None,
) -> dict[str, Any]:
    """Return a port map, filling any ``None`` with ephemeral loopback ports."""
    return {
        "as1_port": as1_port or _free_udp_port(),
        "as2_port": as2_port or _free_udp_port(),
        "return_port": return_port or _free_udp_port(),
        "forward_port": forward_port or _free_udp_port(),
        "terminating_port": terminating_port or _free_udp_port(),
        "pcscf_port": pcscf_port or _free_udp_port(),
    }


def main(argv: list[str] | None = None) -> int:
    """Print one JSON object with chained-runtime ports."""
    parser = argparse.ArgumentParser(description="Phase 3 chained port allocator")
    parser.add_argument("--as1-port", type=int, default=None)
    parser.add_argument("--as2-port", type=int, default=None)
    parser.add_argument("--return-port", type=int, default=None)
    parser.add_argument("--forward-port", type=int, default=None)
    parser.add_argument("--terminating-port", type=int, default=None)
    parser.add_argument("--pcscf-port", type=int, default=None)
    args = parser.parse_args(argv)
    ports = allocate_chained_ports(
        as1_port=args.as1_port,
        as2_port=args.as2_port,
        return_port=args.return_port,
        forward_port=args.forward_port,
        terminating_port=args.terminating_port,
        pcscf_port=args.pcscf_port,
    )
    ports["ingress_port"] = ports["as1_port"]
    print(json.dumps(ports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
