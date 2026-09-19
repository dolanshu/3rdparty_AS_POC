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

"""Probe sippy's ``608 Rejected`` reject path over real UDP.

P8's reject semantics rest on one design assumption (``docs/phase2-plan.md`` section 3,
P8 "First steps"): that sippy emits an arbitrary 6xx through the
``CCEventFail((status, phrase, None))`` path the AS already uses for ``404`` and ``603``.
``608 Rejected`` (RFC 8688) is not among the codes the stack has ever emitted, so it is
observed here rather than assumed (``AGENT.md`` section 6).

The probe runs the same primitives the AS runs — ``SipConf``,
``SipTransactionManager``, ``ED2.loop()`` and a ``UA`` per INVITE — terminates one INVITE
on its answering leg and fails it with a ``CCEventFail`` carrying the requested status and
phrase. It prints the request it sent, the response that actually came back and the
handler path it took. ``CallController._reject_on_trunk`` is the production code this
mirrors.

Usage:
    uv run python tools/anti_fraud_probe.py
    uv run python tools/anti_fraud_probe.py --status 608 --phrase Rejected
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

#: Minimal INVITE as it would arrive on the trunk (RFC 3261 section 11.1). The
#: ``Feature-Caps: *;+sip.608`` header is the capability token RFC 8688 section 3.4
#: expects from a UAC that accepts a 608; the probe sends it so the exchange matches what
#: the mock S-SBC declares. The probe sends this from a plain UDP socket, so the header is
#: written here verbatim rather than rendered by sippy.
INVITE_TEMPLATE = (
    "INVITE sip:{called}@{host}:{port};user=phone SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {client}:{client_port};branch=z9hG4bK608probe0001;rport\r\n"
    "Max-Forwards: 70\r\n"
    "From: <sip:{caller}@{client}>;tag=608probe-from-0001\r\n"
    "To: <sip:{called}@{host}>\r\n"
    "Call-ID: 608probe-{stamp}@example.invalid\r\n"
    "CSeq: 1 INVITE\r\n"
    "Contact: <sip:{client}:{client_port}>\r\n"
    "Feature-Caps: *;+sip.608\r\n"
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


def _is_final_response(data: bytes) -> bool:
    """Tell whether a datagram is a final (non-``1xx``) SIP response.

    The answering leg sends ``100 Trying`` as soon as the INVITE is terminated, so the
    client has to keep reading until the status line carries a code of ``200`` or above.

    Args:
        data: One received datagram.

    Returns:
        ``True`` when the datagram is a SIP response with a status code of ``200`` or more.
    """
    first_line = data.decode(errors="replace").split("\r\n", 1)[0]
    fields = first_line.split(" ", 2)
    if len(fields) < 2 or fields[0] != "SIP/2.0":
        return False
    try:
        return int(fields[1]) >= 200
    except ValueError:
        return False


def run_probe(status: int = 608, phrase: str = "Rejected") -> int:
    """Run the reject-path probe and print the observed exchange.

    Args:
        status: SIP status code the answering leg fails the call with.
        phrase: Reason phrase carried with that status code.

    Returns:
        ``0`` when the response carried the requested status, ``1`` otherwise.
    """
    from sippy.CCEvents import CCEventFail, CCEventTry
    from sippy.Core.EventDispatcher import ED2
    from sippy.SipAddress import SipAddress
    from sippy.SipConf import SipConf
    from sippy.SipContact import SipContact
    from sippy.SipLogger import SipLogger
    from sippy.SipTransactionManager import SipTransactionManager
    from sippy.SipURL import SipURL
    from sippy.UA import UA

    host = "127.0.0.1"
    stack_port = _free_udp_port()
    client_port = _free_udp_port()
    handler_path: list[str] = []

    # The probe is the only sippy application in this process, so it can write the
    # process-wide identity directly instead of pinning it around each message.
    SipConf.my_uaname = "AS POC anti-fraud probe"
    SipConf.my_address = host
    SipConf.my_port = stack_port
    global_config = {
        "nh_addr": (host, stack_port),
        "_sip_address": host,
        "_sip_port": stack_port,
        "_sip_uaname": "AS POC anti-fraud probe",
        "_sip_logger": SipLogger("anti-fraud-probe"),
    }

    def on_event(event, ua):  # type: ignore[no-untyped-def] # sippy callback signature
        """Fail the call on the answering leg, as ``_reject_on_trunk`` does.

        Args:
            event: A sippy ``CCEvent``.
            ua: The answering UA the event came from.
        """
        if isinstance(event, CCEventTry):
            handler_path.append(f"CCEventTry -> CCEventFail(({status}, {phrase!r}, None))")
            ua.recvEvent(CCEventFail((status, phrase, None)))

    def recv_request(req, sip_t):  # type: ignore[no-untyped-def] # sippy callback signature
        """Terminate the INVITE on a fresh answering leg.

        Args:
            req: The parsed SIP request.
            sip_t: The server transaction.

        Returns:
            The sippy callback triple produced by the answering leg.
        """
        ua = UA(global_config, on_event)
        ua.local_ua = "AS POC anti-fraud probe"
        ua.lContact = SipContact(
            address=SipAddress(
                url=SipURL(host=host, port=stack_port, transport=SipConf.my_transport)
            )
        )
        return ua.recvRequest(req, sip_t)

    print(f"python      : {sys.version.split()[0]}")
    print(f"sippy       : {version('sippy')}")
    print(f"stack port  : {host}:{stack_port}  (client port {client_port})")
    print(f"reject      : {status} {phrase}  via CCEventFail((status, phrase, None))")

    manager = SipTransactionManager(global_config, recv_request)
    global_config["_sip_tm"] = manager

    # ED2.loop() owns the main thread, exactly as it does in the AS process: sippy timers
    # are created from the loop, so the client side lives on another thread. The client
    # keeps reading until it sees a final (>= 200) response, because the answering leg
    # sends ``100 Trying`` before the ``CCEventFail`` produces the final answer.
    result: dict[str, list[bytes]] = {"responses": []}

    def send_invite() -> None:
        """Send the probe INVITE and stop the loop when the final answer arrives."""
        time.sleep(0.3)  # give the Udp_server a moment to bind inside the loop
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.bind((host, client_port))
            invite = _build_invite("+8613800138000", "+86216180001", host, stack_port, client_port)
            print("--- INVITE sent -------------------------------------------------")
            print(invite.decode().replace("\r\n", "\n").strip())
            client.sendto(invite, (host, stack_port))
            client.settimeout(5.0)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    data, _ = client.recvfrom(65535)
                except TimeoutError:
                    break
                result["responses"].append(data)
                if _is_final_response(data):
                    break
        ED2.breakLoop()

    threading.Thread(target=send_invite, daemon=True).start()
    ED2.loop()

    responses = result["responses"]
    if not responses:
        print("--- verdict --------------------------------------------------------")
        print("no response within 5 seconds")
        return 1
    print("--- responses received -------------------------------------------")
    for index, data in enumerate(responses, start=1):
        print(f"[{index}] " + data.decode(errors="replace").replace("\r\n", "\n").strip())
    for line in handler_path:
        print(f"handler: {line}")
    final_line = responses[-1].decode(errors="replace").split("\r\n", 1)[0]
    print("--- verdict --------------------------------------------------------")
    print(f"final status line: {final_line}")
    ok = final_line.startswith("SIP/2.0") and str(status) in final_line
    print(f"CCEventFail {status} reject path: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """Run the probe.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Probe the sippy 608 reject path on loopback")
    parser.add_argument("--status", type=int, default=608, help="status code to fail with")
    parser.add_argument("--phrase", default="Rejected", help="reason phrase to fail with")
    args = parser.parse_args(argv)
    return run_probe(args.status, args.phrase)


if __name__ == "__main__":
    raise SystemExit(main())
