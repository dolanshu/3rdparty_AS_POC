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

"""Shared bootstrap for chained topology demos, probes and test fixtures."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from capture_call import free_udp_port, rewrite_next_hop_ports
from sippy.Core.EventDispatcher import ED2
from sippy.Time.Timeout import Timeout

from anti_fraud_as.bootstrap import FraudAsSettings
from anti_fraud_as.main import FraudAsStack
from as_app.bootstrap import AsSettings
from as_app.main import AsStack
from as_app.observability.metrics import MetricsRegistry
from as_app.observability.tracing import SipMessageRecorder, TraceRecorder
from ims_mock.chained_stack import ChainedImsStack
from s_sbc_mock.uac import CallOutcome, CallScenario

TRUNK_ADDRESS = "127.0.0.1"
POLL_SECONDS = 0.02
CALL_TIMEOUT_SECONDS = 15.0
_LABEL_WIDTH = 18
_CHARGING_VECTOR_HEADER = "p-charging-vector"


def draw_loop_until(predicate: Any, timeout_seconds: float = CALL_TIMEOUT_SECONDS) -> bool:
    """Drive the sippy event loop until a condition holds or the timeout expires."""
    state = {"done": False}

    def poll() -> None:
        if predicate():
            state["done"] = True
            ED2.breakLoop()

    timer = Timeout(poll, POLL_SECONDS, -1)
    deadline = Timeout(ED2.breakLoop, timeout_seconds, 1)
    try:
        ED2.loop(timeout=timeout_seconds)
    finally:
        timer.cancel()
        deadline.cancel()
    return bool(state["done"] or predicate())


def verdict_attributes(stack: FraudAsStack, call_id: str) -> dict[str, Any]:
    """Return trace attributes of the verdict event for one call."""
    for event in stack.tracer.trace_for(call_id).events:
        if event.method == "verdict":
            return dict(event.attributes)
    return {}


def decision_rule(stack: AsStack, call_id: str) -> str | None:
    """Return the routing rule AS-2 applied to a call."""
    for event in stack.tracer.trace_for(call_id).events:
        if event.rule_id:
            return event.rule_id
    return None


def _icid_of(value: str | None) -> str | None:
    if not value:
        return None
    for parameter in value.split(";"):
        key, _, parameter_value = parameter.partition("=")
        if key.strip().lower() == "icid-value":
            return parameter_value.strip()
    return None


def _header_value(headers: dict[str, str] | None, name: str) -> str | None:
    for header_name, header_value in (headers or {}).items():
        if header_name.lower() == name:
            return header_value
    return None


def received_invite_icid(recorder: SipMessageRecorder) -> str | None:
    """Return the ICID of the first recorded inbound INVITE."""
    for message in recorder.messages:
        if message.direction != "in" or not message.text.upper().startswith("INVITE"):
            continue
        for line in message.text.splitlines():
            header_name, _, header_value = line.partition(":")
            if header_name.strip().lower() == _CHARGING_VECTOR_HEADER:
                return _icid_of(header_value)
    return None


def build_chained_stack(
    *,
    screening_file: Path,
    rules_file: Path,
    rules_dir: Path,
    allowed_peers: list[str] | None = None,
) -> ChainedImsStack:
    """Allocate ports, build AS instances and wire the iFC-orchestrated chain.

    Args:
        screening_file: Screening YAML for AS-1.
        rules_file: Routing catalogue for AS-2.
        rules_dir: Directory for rewritten rules (next hop -> return port).
        allowed_peers: Trunk peers accepted by both AS instances.

    Returns:
        A started :class:`ChainedImsStack`.
    """
    as1_port = free_udp_port()
    as2_port = free_udp_port()
    return_port = free_udp_port()
    forward_port = free_udp_port()
    terminating_port = free_udp_port()
    pcscf_port = free_udp_port()
    peers = list(allowed_peers or [TRUNK_ADDRESS])
    chained_rules = rewrite_next_hop_ports(rules_file, return_port, rules_dir)
    as1_messages = SipMessageRecorder()
    as2_messages = SipMessageRecorder()
    as1 = FraudAsStack(
        FraudAsSettings(
            _env_file=None,
            fraud_sip_listen_address=TRUNK_ADDRESS,
            fraud_sip_listen_port=as1_port,
            fraud_sbc_peer_address=TRUNK_ADDRESS,
            fraud_sbc_peer_port=return_port,
            fraud_allowed_peers=peers,
            fraud_screening_file=screening_file,
            log_payloads=False,
        ),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
        sip_logger=as1_messages,
    )
    as2 = AsStack(
        AsSettings(
            _env_file=None,
            sip_listen_address=TRUNK_ADDRESS,
            sip_listen_port=as2_port,
            sbc_peer_address=TRUNK_ADDRESS,
            sbc_peer_port=return_port,
            allowed_peers=peers,
            rules_file=chained_rules,
            log_payloads=False,
        ),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
        sip_logger=as2_messages,
    )
    stack = ChainedImsStack.build(
        as1=as1,
        as2=as2,
        as1_port=as1_port,
        as2_port=as2_port,
        return_port=return_port,
        forward_port=forward_port,
        terminating_port=terminating_port,
        pcscf_port=pcscf_port,
        bind_address=TRUNK_ADDRESS,
        as1_messages=as1_messages,
        as2_messages=as2_messages,
    )
    stack.start()
    return stack


_HEADER_LINE = re.compile(r"^([A-Za-z0-9.\-]+):[ \t]*(.*)$")


def headers_of(message: str) -> dict[str, str]:
    """Parse the header block of a raw SIP message."""
    parsed: dict[str, str] = {}
    head = message.split("\r\n\r\n", 1)[0]
    for line in head.split("\r\n")[1:]:
        match = _HEADER_LINE.match(line)
        if match is not None:
            parsed.setdefault(match.group(1).lower(), match.group(2))
    return parsed


def body_of(message: str) -> str:
    """Return the body of a raw SIP message."""
    parts = message.split("\r\n\r\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def recorded_invites(recorder: Any, direction: str) -> list[Any]:
    """Return INVITEs of one direction from a recorder."""
    return [
        message
        for message in recorder.messages
        if message.direction == direction and message.text.startswith("INVITE ")
    ]


__all__ = [
    "CALL_TIMEOUT_SECONDS",
    "CallOutcome",
    "CallScenario",
    "_LABEL_WIDTH",
    "build_chained_stack",
    "body_of",
    "decision_rule",
    "draw_loop_until",
    "headers_of",
    "received_invite_icid",
    "recorded_invites",
    "verdict_attributes",
]
