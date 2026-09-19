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

"""Integration tests for the chained AS topology on localhost UDP.

Two B2BUA instances in series, ``emulated S-CSCF -> AS-1 (anti-fraud) -> AS-2 (number
translation) -> emulated core``, wired **by configuration only** (REQ-F-026): AS-1's
configured next hop is AS-2's listen address and AS-2's next hop is a routing-catalogue
entry. What is exercised here, on the wire and with ephemeral ports (never 5060 or 5062):

- an INVITE AS-1 **allows** is relayed into AS-2, translated there and answered by the core,
  with the SDP body and the pass-through headers surviving both hops (REQ-F-025);
- every leg derives its **own** dialog ``Call-ID``, so the call carries three distinct values
  and each instance keys its trace on the value it saw on its own trunk leg (REQ-NF-016,
  REQ-F-028);
- a call AS-1 **rejects** is answered ``608`` on the trunk and never reaches AS-2 or the
  core — the absence of the second leg is the assertion, not just the status code
  (REQ-F-027).

Covers ACC-P9-001 (REQ-F-025, REQ-F-026), ACC-P9-002 (REQ-F-027) and ACC-P9-003
(REQ-F-028, REQ-NF-016).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from as_app.sip_adapter import PASSTHROUGH_HEADERS, outbound_call_id
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.integration

#: A caller the shipped screening data does not list, so AS-1 relays the call.
ALLOWED_CALLER = "+86216180001"

#: A caller the shipped screening data blocks (first entry of the block list).
BLOCKED_CALLER = "+8613400000001"

#: Called number of every call here: AS-1 never rewrites it, AS-2 translates it.
CALLED_NUMBER = "+8613800138000"

#: The translated number the core receives (+8613800138000, ``+86`` stripped, ``0`` added).
TRANSLATED_NUMBER = "013800138000"

_HEADER_LINE = re.compile(r"^([A-Za-z0-9.\-]+):[ \t]*(.*)$")


def headers_of(message: str) -> dict[str, str]:
    """Parse the header block of a raw SIP message.

    Args:
        message: A complete SIP message.

    Returns:
        A mapping from lower case header name to value; a repeated header keeps the first.
    """
    parsed: dict[str, str] = {}
    head = message.split("\r\n\r\n", 1)[0]
    for line in head.split("\r\n")[1:]:
        match = _HEADER_LINE.match(line)
        if match is not None:
            parsed.setdefault(match.group(1).lower(), match.group(2))
    return parsed


def body_of(message: str) -> str:
    """Return the body of a raw SIP message.

    Args:
        message: A complete SIP message.

    Returns:
        The body without trailing whitespace, empty when there is none.
    """
    parts = message.split("\r\n\r\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def recorded_invites(recorder: Any, direction: str) -> list[Any]:
    """Return the INVITEs of one direction recorded on the wire.

    Args:
        recorder: A ``SipMessageRecorder``.
        direction: ``in`` for a message the instance received, ``out`` for one it sent.

    Returns:
        The matching recorded messages, in the order they were seen.
    """
    return [
        message
        for message in recorder.messages
        if message.direction == direction and message.text.startswith("INVITE ")
    ]


def test_an_allowed_call_traverses_both_b2bus_and_is_translated(chained_pair_factory) -> None:
    """AS-1 relays, AS-2 translates, the core answers: one call through two B2BUAs.

    The chain is configuration only (REQ-F-026): AS-1's peer knob points at AS-2's listen
    address and AS-2's catalogue entry selects the core. What proves the relay crossed both
    instances is the far end: the core saw exactly one INVITE, carrying AS-2's translated
    number, the same SDP body and the same pass-through headers AS-1 received.
    """
    pair = chained_pair_factory()
    scenario = CallScenario(
        name="chain-allow", calling_number=ALLOWED_CALLER, called_number=CALLED_NUMBER
    )
    call_id = pair.place_call(scenario)
    outcome = pair.outcome_for(call_id)
    assert outcome is not None

    finished = pair.run_until(lambda: (pair.outcome_for(call_id) or outcome).released)
    outcome = pair.outcome_for(call_id) or outcome

    assert finished, f"the chained call {call_id} did not finish within the timeout"
    assert outcome.status == 200, f"the caller saw {outcome.status} instead of 200 OK"
    assert outcome.released is True

    invites = list(pair.mock.uas.received_invites)
    assert len(invites) == 1, f"the core received {len(invites)} INVITEs, expected exactly 1"
    received = invites[0]
    assert received.called_number == TRANSLATED_NUMBER, (
        f"the core received {received.called_number}, expected {TRANSLATED_NUMBER}"
    )
    assert received.request_uri.startswith(f"sip:{TRANSLATED_NUMBER}@")

    # SDP and the pass-through headers survive both B2BUs: compare what AS-1 received on its
    # trunk leg with what the core received at the far end of the chain.
    inbound = recorded_invites(pair.as_messages, "in")
    assert len(inbound) == 1, f"expected one inbound INVITE at AS-1, got {len(inbound)}"
    sent = headers_of(inbound[0].text)
    assert received.body == body_of(inbound[0].text), "the SDP body changed across the chain"
    assert received.body == scenario.sdp_offer.strip()
    exercised = [name for name in PASSTHROUGH_HEADERS if name in sent]
    assert "p-asserted-identity" in exercised
    relayed = received.headers or {}
    for name in exercised:
        assert relayed.get(name) == sent[name], (
            f"header {name} changed across the chain: {sent[name]!r} -> {relayed.get(name)!r}"
        )


def test_every_leg_regenerates_its_call_id_and_each_instance_keys_its_trace(
    chained_pair_factory,
) -> None:
    """Three distinct Call-IDs, one per leg, read off the wire (REQ-NF-016, REQ-F-028).

    The identities are read from the recorded messages and the core's received INVITE, not
    inferred from the controller: the trunk leg, AS-1's inter-AS leg and AS-2's core leg each
    carry a value derived from the previous one, so the chain has **no** shared key. Each
    instance still keys its trace on the Call-ID of its own trunk leg, which is what makes
    the call observable per instance.
    """
    pair = chained_pair_factory()
    scenario = CallScenario(
        name="chain-call-ids", calling_number=ALLOWED_CALLER, called_number=CALLED_NUMBER
    )
    trunk_call_id = pair.place_call(scenario)
    outcome = pair.outcome_for(trunk_call_id)
    assert outcome is not None
    finished = pair.run_until(lambda: (pair.outcome_for(trunk_call_id) or outcome).released)
    assert finished, f"the chained call {trunk_call_id} did not finish within the timeout"

    inbound = recorded_invites(pair.as_messages, "in")
    outbound = recorded_invites(pair.as_messages, "out")
    assert len(inbound) == 1, f"expected one inbound INVITE at AS-1, got {len(inbound)}"
    assert len(outbound) == 1, f"expected one outbound INVITE at AS-1, got {len(outbound)}"
    assert pair.mock.uas.received_invites, "no INVITE reached the core side"

    trunk_wire = str(inbound[0].call_id)
    inter_as_wire = str(outbound[0].call_id)
    core_wire = str(pair.mock.uas.received_invites[0].call_id)

    assert trunk_wire == trunk_call_id
    assert inter_as_wire == outbound_call_id(trunk_wire)
    assert core_wire == outbound_call_id(inter_as_wire)
    assert len({trunk_wire, inter_as_wire, core_wire}) == 3, (
        "the chain must carry three distinct Call-IDs, got "
        f"{trunk_wire!r}, {inter_as_wire!r}, {core_wire!r}"
    )

    # Each instance keys its trace on the Call-ID of its own trunk leg...
    assert pair.as_stack.tracer.trace_for(trunk_wire).events, (
        "AS-1 did not key its trace on the S-CSCF's Call-ID"
    )
    assert pair.second_as.tracer.trace_for(inter_as_wire).events, (
        "AS-2 did not key its trace on the Call-ID AS-1 sent"
    )
    # ...and on no other value of this call, which is why the two feeds do not correlate.
    assert not pair.as_stack.tracer.trace_for(inter_as_wire).events, (
        "AS-1 keyed a trace on AS-2's Call-ID"
    )
    assert not pair.second_as.tracer.trace_for(trunk_wire).events, (
        "AS-2 keyed a trace on the S-CSCF's Call-ID"
    )


def test_a_reject_at_as1_short_circuits_before_as2_and_the_core(chained_pair_factory) -> None:
    """A ``608`` at AS-1 is an absence at AS-2 and the core, not just a status code.

    The reject path is UAS-only (REQ-F-027): AS-1 answers the INVITE itself and originates no
    second leg, so the chain must show zero new calls at AS-2 and zero INVITEs at the core.
    The deltas are taken before and after, so the assertion is on this call and not on the
    state of a fresh pair.
    """
    pair = chained_pair_factory()
    as2_before = len(pair.second_as.tracer.known_call_ids())
    core_before = len(pair.mock.uas.received_invites)

    scenario = CallScenario(
        name="chain-reject",
        calling_number=BLOCKED_CALLER,
        called_number=CALLED_NUMBER,
        expect_status=608,
    )
    call_id = pair.place_call(scenario)
    outcome = pair.outcome_for(call_id)
    assert outcome is not None
    finished = pair.run_until(lambda: (pair.outcome_for(call_id) or outcome).released)
    outcome = pair.outcome_for(call_id) or outcome

    assert finished, f"the rejected call {call_id} did not finish within the timeout"
    assert outcome.status == 608, f"the caller saw {outcome.status} instead of 608"
    assert outcome.released is True

    # The full "608 Rejected" status line goes over the wire (LLD section 9.5).
    response_lines = [
        message.text.split("\r\n", 1)[0]
        for message in pair.as_messages.messages_for_any((call_id, outbound_call_id(call_id)))
        if message.direction == "out" and message.text.startswith("SIP/2.0 ")
    ]
    assert "SIP/2.0 608 Rejected" in response_lines, (
        f"the wire did not carry 'SIP/2.0 608 Rejected': {response_lines}"
    )

    assert len(pair.second_as.tracer.known_call_ids()) - as2_before == 0, (
        "a rejected call must not create any call state at AS-2"
    )
    assert len(pair.mock.uas.received_invites) - core_before == 0, (
        "a rejected call must not originate an INVITE towards the core"
    )
