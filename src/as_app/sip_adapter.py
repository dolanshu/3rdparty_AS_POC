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

"""Thin wrapper around the sippy primitives.

This is the only place, together with :mod:`as_app.call_controller`, that is allowed to
touch sippy objects. Everything above the adapter talks in plain Python values, so the
translation and routing logic stays testable without a stack (``AGENT.md`` section 12).

The URI and header handling here follows RFC 3261: a Request-URI of the form
``sip:user@host`` and the ``P-Asserted-Identity`` header carrying the calling party on an
IMS trunk (3GPP TS 24.229).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any, Final

from as_app.errors import AsError, AsErrorCode
from as_app.routing.rules import NextHop

__all__ = [
    "B2BUA_CALL_ID_SUFFIX",
    "PASSTHROUGH_HEADERS",
    "TRANSACTION_TIMER_NAMES",
    "CallLeg",
    "TrunkMessage",
    "build_request_uri",
    "cancel_transaction_timers",
    "extract_called_number",
    "is_allowed_peer",
    "outbound_call_id",
]

#: ``sip:+8613800100000@10.0.0.1:5060;user=phone`` -> ``+8613800100000``.
#: The ``@`` is required: a URI without a user part (``sip:10.0.0.1``) is a host only URI
#: and must be reported as a malformed request, not treated as a number.
_USER_FROM_URI = re.compile(r"^sips?:([^@;?]+)@")

#: Headers the B2BUA copies verbatim from the trunk leg to the next-hop leg
#: (``AGENT.md`` section 1: "SDP bodies and SIP headers are passed through verbatim").
#:
#: The list is deliberately explicit and excludes everything the stack itself owns or
#: regenerates: ``Via``, ``Route``, ``Record-Route``, ``Contact``, ``Max-Forwards``,
#: ``Content-Length`` (hop by hop) and ``From``, ``To``, ``Call-ID``, ``CSeq`` (dialog,
#: regenerated for the second leg). ``User-Agent`` is the identity of the AS, not a
#: pass-through header, and ``Content-Type`` follows the body.
#:
#: Documented in ``docs/architecture/lld.md`` section 2.3; the integration test
#: ``tests/integration/test_signalling_path.py`` asserts that every header listed here
#: arrives unchanged on the far side.
PASSTHROUGH_HEADERS: Final[tuple[str, ...]] = (
    "p-asserted-identity",
    "p-preferred-identity",
    "privacy",
    "p-charging-vector",
    "p-charging-function-addresses",
    "p-visited-network-id",
    "subject",
    "organization",
    "priority",
)

#: Suffix the AS appends to the trunk Call-ID when it originates the second leg, so the
#: outbound leg carries its own dialog identity instead of reusing the trunk one. It
#: follows sippy's own ``CCB2BUA``, which rewrites the Call-ID as
#: ``'<call-id>-b2b_%d' % oroute.rnum`` (``sippy/b2bua.py``); route ``1`` is the AS's
#: single outbound leg. The AS runs its own controller plus a bare ``sippy.UA``, not
#: ``CCB2BUA``, so nothing else rewrites the Call-ID for it. See
#: ``docs/architecture/lld.md`` section 2.3.
B2BUA_CALL_ID_SUFFIX: Final[str] = "-b2b_1"

#: The per-transaction timer attributes of sippy's ``SipTransaction``, named after the
#: timer roles in its own code: ``teA`` retransmits a request (and a final response on a
#: server transaction), ``teB``…``teG`` bound how long a transaction is kept alive
#: (RFC 3261 section 17). Every one of them is owned by the transaction, not by the
#: manager, so ``SipTransactionManager.shutdown()`` cancels none of them.
TRANSACTION_TIMER_NAMES: Final[tuple[str, ...]] = (
    "teA",
    "teB",
    "teC",
    "teD",
    "teE",
    "teF",
    "teG",
)


@dataclass(frozen=True)
class CallLeg:
    """One side of a B2BUA call.

    Attributes:
        leg: ``in`` for the trunk leg towards the S-SBC, ``out`` for the leg towards the
            next hop.
        call_id: SIP Call-ID of the dialog.
        local_address: Local address of the leg.
        remote_address: Peer address of the leg.
    """

    leg: str
    call_id: str
    local_address: str
    remote_address: str


@dataclass(frozen=True)
class TrunkMessage:
    """The AS-facing view of a SIP message received on the trunk.

    Attributes:
        method: SIP method, for example ``INVITE``.
        call_id: SIP Call-ID, the correlation key of the call.
        request_uri: Request-URI as received.
        called_number: User part of the Request-URI.
        calling_number: Calling party from ``P-Asserted-Identity``, when present.
        source_address: Address the message came from.
        headers: Relevant headers, verbatim.
        body: Message body, carried through unmodified (SDP pass-through).
    """

    method: str
    call_id: str
    request_uri: str
    called_number: str
    calling_number: str | None = None
    source_address: str = "-"
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""


def cancel_transaction_timers(transaction_manager: Any) -> int:
    """Cancel every per-transaction timer of a sippy transaction manager.

    ``SipTransactionManager.shutdown()`` cancels only its own cache-purge timer
    (``cp_timer``) and releases the UDP sockets, so every timer a transaction still owns
    stays armed in the process-wide ``ED2`` loop, which nothing stops with the manager.
    Such a timer fires into a manager whose ``global_config`` is already ``None`` and
    raises ``TypeError: 'NoneType' object is not subscriptable`` in ``transmitData`` —
    which is exactly why a retransmission that was pending when a manager stopped could
    break an unrelated test sharing the same loop. Cancelling them first makes the
    shutdown complete.

    It has to happen *before* ``shutdown()``: that call drops the transaction tables the
    timers hang from, so afterwards there is nothing left to walk.

    A server transaction only carries the timer attributes its own branch of RFC 3261
    uses, so a missing attribute is skipped rather than treated as an error. An attribute
    left pointing at a timer that has already fired is skipped too: ``ED2`` nulls the
    callback when a timer has run, so the timer is dead and only the reference remains.

    Args:
        transaction_manager: A sippy ``SipTransactionManager``, live or already stopped.

    Returns:
        The number of timers cancelled, ``0`` when nothing was pending.
    """
    cancelled = 0
    for table_name in ("tclient", "tserver"):
        transactions = getattr(transaction_manager, table_name, None)
        if not transactions:
            continue
        for transaction in list(transactions.values()):
            for timer_name in TRANSACTION_TIMER_NAMES:
                timer = getattr(transaction, timer_name, None)
                if timer is None or getattr(timer, "cb_func", None) is None:
                    continue
                timer.cancel()
                setattr(transaction, timer_name, None)
                cancelled += 1
    return cancelled


def extract_called_number(request_uri: str) -> str:
    """Return the user part of a SIP or SIPS URI.

    Args:
        request_uri: A Request-URI such as ``sip:+8613800100000@10.0.0.1;user=phone``.

    Returns:
        The user part of the URI.

    Raises:
        AsError: ``AS-PEER-003`` when the URI has no user part.
    """
    match = _USER_FROM_URI.match(request_uri.strip())
    if match is None:
        raise AsError(
            AsErrorCode.PEER_MALFORMED_REQUEST,
            f"request-uri has no user part: {request_uri!r}",
            context={"request_uri": request_uri},
        )
    return match.group(1)


def build_request_uri(number: str, hop: NextHop) -> str:
    """Build the Request-URI of the outbound INVITE (RFC 3261 section 19.1).

    Args:
        number: Translated called number.
        hop: Next hop the INVITE is sent to.

    Returns:
        A SIP URI of the form ``sip:<number>@<host>:<port>;transport=udp``.
    """
    host = hop.address if _is_ipv6(hop.address) is False else f"[{hop.address}]"
    return f"sip:{number}@{host}:{hop.port};transport={hop.transport}"


def outbound_call_id(trunk_call_id: str) -> str:
    """Return the Call-ID the AS originates its second leg with.

    ``From``, ``To`` and ``CSeq`` are regenerated by sippy for the outbound dialog, but a
    non-``None`` Call-ID in the ``CCEventTry`` is copied verbatim
    (``sippy/UacStateIdle.py``), so the AS derives one itself instead. Deriving it keeps
    the trunk leg's identity untouched and lets a capture or a test correlate the messages
    of both legs of one call.

    Args:
        trunk_call_id: Call-ID received on the trunk leg.

    Returns:
        ``"<trunk Call-ID>-b2b_1"`` (see :data:`B2BUA_CALL_ID_SUFFIX`).
    """
    return f"{trunk_call_id}{B2BUA_CALL_ID_SUFFIX}"


def _is_ipv6(address: str) -> bool:
    """Tell whether an address literal is IPv6.

    Args:
        address: Address literal or host name.

    Returns:
        ``True`` when the address parses as an IPv6 address.
    """
    try:
        return ip_address(address).version == 6
    except ValueError:
        return False


def is_allowed_peer(source_address: str, allowed_peers: list[str]) -> bool:
    """Check a trunk source address against the allowlist.

    The trunk is treated as untrusted: a message from an address that is not configured
    is rejected with ``403`` and ``AS-PEER-001`` (``AGENT.md`` section 9).

    Args:
        source_address: Source IP address of the message.
        allowed_peers: Configured peer addresses.

    Returns:
        ``True`` when the source is an allowed peer.
    """
    return source_address in allowed_peers
