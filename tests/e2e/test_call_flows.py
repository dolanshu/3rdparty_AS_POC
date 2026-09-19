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

"""End-to-end call flows.

The e2e layer drives a complete call through the AS and the mock S-SBC on localhost UDP
and asserts on the messages that arrive on the far side, including the error branches
(``AGENT.md`` section 11). Every case prints a Call-ID keyed trace, so a run of this file
is usable as demo evidence on its own.

The number translation and the ``404`` / ``603`` error branches are delivered in **M2**
(``AGENT.md`` section 15); this file covers the complete call, caller abandonment
(``CANCEL``), the translation assertion and the two error branches.
"""

from __future__ import annotations

import pytest

from as_app.observability.tracing import CallTrace
from as_app.sip_adapter import outbound_call_id
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.e2e


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

    # The core side of the mock is the far end: it must see the very same call, with the
    # called number translated by the routing engine (M2). +8613800138000 is a China
    # Mobile E.164 number; rule R-MOB-CM-40 strips +86 and prepends 0, so the Request-URI
    # the core receives carries 013800138000.
    invites = list(trunk_pair.mock.uas.received_invites)
    assert invites, "no INVITE reached the core side of the mock"
    received = invites[0]
    # The core side sees the AS's own outbound Call-ID, derived from the trunk one with
    # sippy's `-b2b_1` suffix (the second leg has its own dialog identity).
    assert received.call_id == outbound_call_id(call_id)
    assert received.called_number == "013800138000", (
        f"expected translated number 013800138000, got {received.called_number}"
    )
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


def test_request_uri_carries_the_translated_number(trunk_pair) -> None:
    """The outbound Request-URI carries the translated called number (ACC-M2-001).

    ``+8613800138000`` is a China Mobile E.164 number; rule ``R-MOB-CM-40`` strips
    ``+86`` and prepends ``0``, so the core side receives ``013800138000``.
    """
    scenario = CallScenario(
        name="translation",
        calling_number="+86216180001",
        called_number="+8613800138000",
    )
    call_id = trunk_pair.place_call(scenario)
    outcome = trunk_pair.outcome_for(call_id)
    assert outcome is not None
    finished = trunk_pair.run_until(lambda: (trunk_pair.outcome_for(call_id) or outcome).released)
    outcome = trunk_pair.outcome_for(call_id) or outcome
    assert finished, f"call {call_id} did not finish within the timeout"

    invites = list(trunk_pair.mock.uas.received_invites)
    assert invites, "no INVITE reached the core side of the mock"
    received = invites[0]
    assert received.called_number == "013800138000", (
        f"expected translated number 013800138000, got {received.called_number}"
    )
    assert received.request_uri.startswith("sip:013800138000@")

    trace = trunk_pair.as_stack.tracer.trace_for(call_id)
    decisions = [e for e in trace.events if e.method == "decision"]
    assert decisions, "the routing decision is not part of the trace"
    assert decisions[0].rule_id == "R-MOB-CM-40"
    assert decisions[0].attributes.get("translated_number") == "013800138000"

    counters = trunk_pair.as_stack.metrics.snapshot()
    # The metrics registry is process-wide and shared across e2e cases, so the counter
    # accumulates: assert the rule was hit at least once for this call.
    assert (counters.rule_hits.get("R-MOB-CM-40") or 0) >= 1


def test_unmatched_number_is_answered_with_404(trunk_pair) -> None:
    """A called number no rule accepts is answered with 404 and AS-ROUTE-001."""
    scenario = CallScenario(
        name="no-match",
        calling_number="+86216180001",
        called_number="+9991234567",
        expect_status=404,
    )
    call_id = trunk_pair.place_call(scenario)
    outcome = trunk_pair.outcome_for(call_id)
    assert outcome is not None
    finished = trunk_pair.run_until(lambda: (trunk_pair.outcome_for(call_id) or outcome).released)
    outcome = trunk_pair.outcome_for(call_id) or outcome
    assert finished, f"call {call_id} did not finish within the timeout"
    assert outcome.status == 404, f"caller saw {outcome.status} instead of 404"

    trace = trunk_pair.as_stack.tracer.trace_for(call_id)
    print(render_trace(trace))
    decisions = [e for e in trace.events if e.method == "decision"]
    assert decisions, "the no-match decision is not part of the trace"
    # The 404 response is relayed to the trunk leg.
    assert any(e.method == "404" for e in trace.events), (
        "the 404 response is not in the Call-ID keyed trace"
    )

    counters = trunk_pair.as_stack.metrics.snapshot()
    assert counters.errors_by_code.get("AS-ROUTE-001") == 1
    assert counters.calls_by_disposition.get("no_match") == 1
    # No INVITE reaches the core side when the call is rejected.
    assert not trunk_pair.mock.uas.received_invites, (
        "a 404 call must not originate an INVITE towards the core"
    )


def test_blocked_number_is_answered_with_603(trunk_pair) -> None:
    """A policy rejection is answered with 603 Decline and AS-ROUTE-002."""
    scenario = CallScenario(
        name="blocked",
        calling_number="+86216180001",
        called_number="+861681234567",
        expect_status=603,
    )
    call_id = trunk_pair.place_call(scenario)
    outcome = trunk_pair.outcome_for(call_id)
    assert outcome is not None
    finished = trunk_pair.run_until(lambda: (trunk_pair.outcome_for(call_id) or outcome).released)
    outcome = trunk_pair.outcome_for(call_id) or outcome
    assert finished, f"call {call_id} did not finish within the timeout"
    assert outcome.status == 603, f"caller saw {outcome.status} instead of 603"

    trace = trunk_pair.as_stack.tracer.trace_for(call_id)
    print(render_trace(trace))
    decisions = [e for e in trace.events if e.method == "decision"]
    assert decisions, "the reject decision is not part of the trace"
    assert decisions[0].rule_id == "R-BLOCK-90"
    assert any(e.method == "603" for e in trace.events), (
        "the 603 response is not in the Call-ID keyed trace"
    )

    counters = trunk_pair.as_stack.metrics.snapshot()
    assert counters.errors_by_code.get("AS-ROUTE-002") == 1
    assert counters.calls_by_disposition.get("rejected") == 1
    assert not trunk_pair.mock.uas.received_invites, (
        "a 603 call must not originate an INVITE towards the core"
    )
