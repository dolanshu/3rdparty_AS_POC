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

"""End-to-end flows of the anti-fraud AS.

The complete call an operator would demonstrate on the second instance: a screened caller
that is allowed and relayed through ``INVITE → 100 → 180 → 200 OK → ACK → BYE``, and a
screened caller that is rejected with ``608`` and never reaches the core. Each case prints a
Call-ID keyed trace, so a run of this file is usable as demo evidence on its own (the same
contract as the Phase 1 e2e file).

The Phase 1 flows are unchanged by this item: a second AS process adds a use case, not a
behaviour change to the first one.

Covers ACC-P8-001 (REQ-F-016, REQ-F-021) and ACC-P8-002 (REQ-F-017, REQ-F-019).
"""

from __future__ import annotations

import pytest

from as_app.observability.tracing import CallTrace
from as_app.sip_adapter import outbound_call_id
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.e2e

#: A caller the shipped screening data does not list, so the call is relayed.
ALLOWED_CALLER = "+86216180001"

#: A caller the shipped screening data blocks.
BLOCKED_CALLER = "+8613400000001"


def render_trace(trace: CallTrace) -> str:
    """Render one call trace as a readable ladder.

    Args:
        trace: The Call-ID keyed trace of a call.

    Returns:
        A multi-line string, one line per event.
    """
    lines = [f"call-id {trace.call_id}"]
    for event in trace.events:
        leg = event.attributes.get("leg", "-")
        lines.append(
            f"  {event.timestamp.isoformat(timespec='milliseconds')}  "
            f"{event.direction:<8} {leg:<8} {event.method:<7} {event.summary}"
        )
    return "\n".join(lines)


def test_an_allowed_call_runs_invite_to_bye(
    fraud_trunk_pair, capsys: pytest.CaptureFixture[str]
) -> None:
    """A screened caller is relayed: ``INVITE → 100 → 180 → 200 OK → ACK → BYE``.

    The verdict is taken before the outbound leg exists, and once it is *allow* the call is
    an ordinary B2BUA relay with nothing added to the wire (REQ-F-017).
    """
    scenario = CallScenario(
        name="fraud-allowed-call",
        calling_number=ALLOWED_CALLER,
        called_number="+8613800138000",
    )
    call_id = fraud_trunk_pair.place_call(scenario)
    outcome = fraud_trunk_pair.outcome_for(call_id)
    assert outcome is not None

    finished = fraud_trunk_pair.run_until(
        lambda: (fraud_trunk_pair.outcome_for(call_id) or outcome).released
    )
    outcome = fraud_trunk_pair.outcome_for(call_id) or outcome
    trace = fraud_trunk_pair.as_stack.tracer.trace_for(call_id)
    with capsys.disabled():
        print(render_trace(trace))

    assert finished, f"call {call_id} did not finish within the timeout"
    assert outcome.status == 200, f"caller saw {outcome.status} instead of 200 OK"
    assert outcome.released is True

    # The core side of the mock is the far end, and it saw the relayed leg with its own
    # derived Call-ID (not the trunk one) and the same called number: the anti-fraud AS
    # relays, it does not translate (LLD section 2.3, REQ-NF-016).
    invites = list(fraud_trunk_pair.mock.uas.received_invites)
    assert invites, "no INVITE reached the core side of the mock"
    received = invites[0]
    assert received.call_id == outbound_call_id(call_id)
    assert received.call_id != call_id
    assert received.called_number == "+8613800138000"
    assert received.body == scenario.sdp_offer.strip()

    methods = [event.method for event in trace.events]
    assert "INVITE" in methods
    assert "180" in methods
    assert "200" in methods
    assert "BYE" in methods

    decisions = [event for event in trace.events if event.method == "verdict"]
    assert decisions, "the screening verdict is not part of the Call-ID keyed trace"
    assert decisions[0].attributes.get("verdict") == "allow"


def test_a_rejected_call_ends_with_608_and_no_second_leg(
    fraud_trunk_pair, capsys: pytest.CaptureFixture[str]
) -> None:
    """A blocked caller is answered ``608`` on the trunk and nothing is originated.

    The reject path is UAS behaviour, not B2BUA: the AS answers the INVITE itself. The
    observable proof is that the core side of the mock received **no INVITE**, so the call
    has a single leg for its whole lifetime (REQ-F-021).
    """
    scenario = CallScenario(
        name="fraud-rejected-call",
        calling_number=BLOCKED_CALLER,
        called_number="+8613800138000",
        expect_status=608,
    )
    call_id = fraud_trunk_pair.place_call(scenario)
    outcome = fraud_trunk_pair.outcome_for(call_id)
    assert outcome is not None

    finished = fraud_trunk_pair.run_until(
        lambda: (fraud_trunk_pair.outcome_for(call_id) or outcome).released
    )
    outcome = fraud_trunk_pair.outcome_for(call_id) or outcome
    trace = fraud_trunk_pair.as_stack.tracer.trace_for(call_id)
    with capsys.disabled():
        print(render_trace(trace))

    assert finished, f"call {call_id} did not finish within the timeout"
    assert outcome.status == 608, f"caller saw {outcome.status} instead of 608"
    assert outcome.released is True

    # UAS-only: the second leg was never created, so the core saw nothing at all.
    assert not fraud_trunk_pair.mock.uas.received_invites, (
        "a rejected call must not originate an INVITE towards the core"
    )

    methods = [event.method for event in trace.events]
    assert "608" in methods, "the 608 response is not in the Call-ID keyed trace"
    assert "BYE" not in methods, "a rejected call is never established"

    decisions = [event for event in trace.events if event.method == "verdict"]
    assert decisions, "the screening verdict is not part of the Call-ID keyed trace"
    assert decisions[0].attributes.get("verdict") == "reject"
    assert decisions[0].attributes.get("screen_source") == "block_list"

    counters = fraud_trunk_pair.as_stack.metrics.snapshot()
    assert counters.counters["verdict.reject"] == 1
    assert counters.errors_by_code["AS-FRAUD-001"] == 1
    assert counters.calls_by_disposition["rejected"] == 1
