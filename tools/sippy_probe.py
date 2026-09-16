#!/usr/bin/env python3
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

"""Probe the sippy stack and print what it really does.

sippy behaviour in this project is observed, never assumed (`AGENT.md` section 6). This
probe starts the same primitives the AS will use — `SipConf`, `SipTransactionManager` and
`ED2.loop()` — on a loopback port, sends one INVITE through a plain UDP socket, and
prints the answer that comes back. A run without printed evidence is not a verification.

Usage:
    uv run python tools/sippy_probe.py
    uv run python tools/sippy_probe.py --response 404
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from importlib.metadata import version
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Minimal INVITE as it would arrive on the trunk (RFC 3261 section 11.1). The Request-URI
# carries the called number in E.164; the probe sends it from a second loopback port.
INVITE_TEMPLATE = (
    "INVITE sip:{called}@{host}:{port};user=phone SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {client}:{client_port};branch=z9hG4bKprobe0001;rport\r\n"
    "Max-Forwards: 70\r\n"
    "From: <sip:{caller}@{client}>;tag=probe-from-0001\r\n"
    "To: <sip:{called}@{host}>\r\n"
    "Call-ID: probe-{stamp}@example.invalid\r\n"
    "CSeq: 1 INVITE\r\n"
    "Contact: <sip:{client}:{client_port}>\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)


def _free_udp_port() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _build_invite(called: str, caller: str, host: str, port: int, client_port: int) -> bytes:
    """Build the probe INVITE.

    Args:
        called: Called number used in the Request-URI.
        caller: Calling number used in the From header.
        host: Host the INVITE is sent to.
        port: Port the INVITE is sent to.
        client_port: Port the probe sends from.

    Returns:
        The encoded INVITE message.
    """
    return INVITE_TEMPLATE.format(
        called=called,
        caller=caller,
        host=host,
        port=port,
        client=host,
        client_port=client_port,
        stamp=int(time.monotonic() * 1000) % 100000,
    ).encode()


def run_probe(response_code: int = 404) -> int:
    """Run the stack probe and print the observed exchange.

    Args:
        response_code: Status code the probe request handler answers with.

    Returns:
        ``0`` when the probe saw a response, ``1`` otherwise.
    """
    from sippy.Core.EventDispatcher import ED2
    from sippy.SipConf import SipConf
    from sippy.SipLogger import SipLogger
    from sippy.SipTransactionManager import SipTransactionManager

    host = "127.0.0.1"
    stack_port = _free_udp_port()
    client_port = _free_udp_port()
    received: list[str] = []

    def recv_request(req, sip_t):  # type: ignore[no-untyped-def] # sippy callback signature
        """Answer every INVITE with the configured status code.

        Args:
            req: The parsed SIP request.
            sip_t: The server transaction.

        Returns:
            The sippy callback triple ``(response, None, None)``.
        """
        call_id = req.getHFBody("call-id")
        received.append(f"received {req.getMethod()} call-id={call_id}")
        return (req.genResponse(response_code, "Probe"), None, None)

    SipConf.my_uaname = "AS POC sippy probe"
    # SipLogger writes to stderr unless SIPLOG_BEND says otherwise, which is what a probe
    # wants: the sippy message log is part of the evidence.
    global_config = {
        "nh_addr": (host, stack_port),
        "_sip_address": host,
        "_sip_port": stack_port,
        "_sip_logger": SipLogger("probe"),
    }
    print(f"python      : {sys.version.split()[0]}")
    print(f"sippy       : {version('sippy')}")
    print(f"stack port  : {host}:{stack_port}  (client port {client_port})")

    SipTransactionManager(global_config, recv_request)

    # ED2.loop() owns the main thread, exactly as it will in the AS process: sippy timers
    # are created from the loop, so the client side has to live on another thread.
    result: dict[str, bytes | None] = {"response": None}

    def send_invite() -> None:
        """Send the probe INVITE and stop the loop when the answer arrives."""
        time.sleep(0.3)  # give the Udp_server a moment to bind inside the loop
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.bind((host, client_port))
            invite = _build_invite("+8613800138000", "+86216180001", host, stack_port, client_port)
            print("--- INVITE sent -------------------------------------------------")
            print(invite.decode().replace("\r\n", "\n").strip())
            client.sendto(invite, (host, stack_port))
            client.settimeout(5.0)
            try:
                data, _ = client.recvfrom(65535)
            except TimeoutError:
                print("no response within 5 seconds")
            else:
                result["response"] = data
        ED2.breakLoop()

    threading.Thread(target=send_invite, daemon=True).start()
    ED2.loop()

    data = result["response"]
    if data is None:
        return 1
    print("--- response received --------------------------------------------")
    print(data.decode(errors="replace").replace("\r\n", "\n").strip())
    for line in received:
        print(f"handler: {line}")
    first_line = data.decode(errors="replace").split("\r\n", 1)[0]
    print("--- verdict --------------------------------------------------------")
    print(f"first line: {first_line}")
    ok = first_line.startswith("SIP/2.0") and str(response_code) in first_line
    print(f"minimal SipTransactionManager + ED2.loop() stack: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """Run the probe.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Probe the sippy stack on loopback")
    parser.add_argument(
        "--response", type=int, default=404, help="status code the probe answers with"
    )
    args = parser.parse_args(argv)
    return run_probe(args.response)


if __name__ == "__main__":
    raise SystemExit(main())
