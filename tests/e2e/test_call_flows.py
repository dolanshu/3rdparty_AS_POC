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

"""End-to-end call flows.

The e2e layer drives a complete call through the AS and the mock S-SBC on localhost UDP
and asserts on the messages that arrive on the far side, including the error branches
(``AGENT.md`` section 11). Every case prints a Call-ID keyed trace, so a run of this file
is usable as demo evidence on its own.

Scope note: the ``404`` and ``603`` branches need the routing decision of **M2**
(``AGENT.md`` section 15). They stay declared and skipped with an explicit reason rather
than being deleted or faked.
"""

from __future__ import annotations

import pytest

from as_app.observability.tracing import CallTrace
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.e2e

#: Number translation and its error branches are M2; see docs/roadmap.md.
PENDING_M2 = pytest.mark.skip(
    reason="number translation and its 404/603 branches are delivered in M2 (AGENT.md section 15)"
)


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


def test_complete_call_invite_to_bye(trunk_pair, capsys: pytest.CaptureFixture[str]) -> None:
    """INVITE -> 100 -> 180 -> 200 OK -> ACK -> BYE completes with SDP pass-through."""
    scenario = CallScenario(
        name="complete-call",
        calling_number="+86216180001",
        called_number="+8613800138000",
    )
    call_id = trunk_pair.place_call(scenario)
    outcome = trunk_pair.outcome_for(call_id)
    assert outcome is not None

    finished = trunk_pair.run_until(lambda: (trunk_pair.outcome_for(call_id) or outcome).released)
    outcome = trunk_pair.outcome_for(call_id) or outcome
    trace = trunk_pair.as_stack.tracer.trace_for(call_id)
    print(render_trace(trace))
    with capsys.disabled():
        print(render_trace(trace))

    assert finished, f"call {call_id} did not finish within the timeout"
    assert outcome.status == 200, f"caller saw {outcome.status} instead of 200 OK"
    assert outcome.released is True

    # The core side of the mock is the far end: it must see the very same call.
    invites = list(trunk_pair.mock.uas.received_invites)
    assert invites, "no INVITE reached the core side of the mock"
    received = invites[0]
    assert received.call_id == call_id
    assert received.called_number == scenario.called_number
    assert received.body == scenario.sdp_offer.strip()

    # SDP and the pass-through headers survive the B2BUA unchanged.
    assert received.headers["p-asserted-identity"] == "<sip:+86216180001@ims.example.invalid>"
    assert received.headers["subject"] == scenario.name

    methods = [event.method for event in trace.events]
    assert "INVITE" in methods
    assert "180" in methods
    assert "200" in methods
    assert "BYE" in methods


def test_caller_abandonment_sends_cancel(trunk_pair) -> None:
    """A caller that gives up before answer makes the AS tear the outbound leg down."""
    scenario = CallScenario(
        name="abandoned-call",
        calling_number="+86216180001",
        called_number="+8613800138000",
        abandon=True,
        talk_seconds=0.2,
    )
    call_id = trunk_pair.place_call(scenario)
    outcome = trunk_pair.outcome_for(call_id)
    assert outcome is not None

    cancelled = trunk_pair.run_until(
        lambda: (
            (trunk_pair.outcome_for(call_id) or outcome).cancelled
            and (trunk_pair.outcome_for(call_id) or outcome).released
        )
    )
    outcome = trunk_pair.outcome_for(call_id) or outcome
    assert cancelled, f"call {call_id} was not abandoned within the timeout"
    # An abandoned call is never answered.
    assert outcome.status is None

    trace = trunk_pair.as_stack.tracer.trace_for(call_id)
    print(render_trace(trace))
    assert "200" not in [event.method for event in trace.events], (
        "an abandoned call must not be answered with 200 OK"
    )


@PENDING_M2
def test_unmatched_number_is_answered_with_404() -> None:
    """A called number no rule accepts is answered with 404 and AS-ROUTE-001."""
    raise NotImplementedError


@PENDING_M2
def test_blocked_number_is_answered_with_603() -> None:
    """A policy rejection is answered with 603 Decline and AS-ROUTE-002."""
    raise NotImplementedError
