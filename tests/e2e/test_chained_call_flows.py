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

"""End-to-end flows of the chained AS topology.

The complete call an operator would demonstrate on the chain of ``docs/architecture/lld.md``
section 10: an INVITE the anti-fraud AS **allows** is relayed into the number-translation AS,
translated there and answered by the core, running ``INVITE -> 100 -> 180 -> 200 OK -> ACK ->
BYE`` through both instances; and a caller the anti-fraud AS **rejects** is answered ``608``
and never reaches AS-2 or the core.

Both instances are observable for the one call: each writes its **own** Call-ID keyed trace —
AS-1 on the Call-ID the S-CSCF used, AS-2 on the Call-ID AS-1 sent — so a run of this file is
usable as demo evidence on its own (``AGENT.md`` section 11), with AS-1 carrying the screening
verdict and AS-2 the matched routing rule.

Covers ACC-P9-001 (REQ-F-025), ACC-P9-002 (REQ-F-027) and ACC-P9-003 (REQ-F-028, REQ-NF-016).
"""

from __future__ import annotations

from typing import Any

import pytest

from as_app.observability.tracing import CallTrace
from as_app.sip_adapter import outbound_call_id
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.e2e

#: A caller the shipped screening data does not list, so AS-1 relays the call.
ALLOWED_CALLER = "+86216180001"

#: A caller the shipped screening data blocks.
BLOCKED_CALLER = "+8613400000001"

#: Called number of every call here: AS-1 never rewrites it, AS-2 translates it.
CALLED_NUMBER = "+8613800138000"

#: The translated number the core receives (+8613800138000, ``+86`` stripped, ``0`` added).
TRANSLATED_NUMBER = "013800138000"

#: The rule AS-2 matches for ``+8613800138000`` (config/routing_rules.yaml).
MATCHED_RULE = "R-MOB-CM-40"


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


def inter_as_call_id(pair: Any) -> str:
    """Return the Call-ID AS-1 sent to AS-2, read off the wire.

    Args:
        pair: The bound chained pair.

    Returns:
        The Call-ID of the outbound INVITE AS-1 recorded.
    """
    outbound = [
        message
        for message in pair.as_messages.messages
        if message.direction == "out" and message.text.startswith("INVITE ")
    ]
    assert outbound, "AS-1 did not record an outbound INVITE"
    return str(outbound[0].call_id)


def verdict_of(trace: CallTrace) -> str | None:
    """Return the screening verdict recorded in a trace.

    Args:
        trace: The Call-ID keyed trace of a call.

    Returns:
        The verdict attribute of the ``verdict`` event, or ``None`` when there is none.
    """
    for event in trace.events:
        if event.method == "verdict":
            return str(event.attributes.get("verdict"))
    return None


def matched_rule(trace: CallTrace) -> str | None:
    """Return the routing rule recorded in a trace.

    Args:
        trace: The Call-ID keyed trace of a call, as AS-2 saw it.

    Returns:
        The first rule identifier in the trace, or ``None`` when none was recorded.
    """
    for event in trace.events:
        if event.rule_id:
            return event.rule_id
    return None


def test_the_complete_chained_call_runs_invite_to_bye(
    chained_pair_factory, capsys: pytest.CaptureFixture[str]
) -> None:
    """An allowed call completes through both instances, observed per instance.

    The trunk side sees ``200 OK`` and the core sees the translated number, while each AS
    writes its own Call-ID keyed trace of the same call: AS-1 carries the screening verdict
    and AS-2 the matched rule (REQ-F-025, REQ-F-028).
    """
    pair = chained_pair_factory()
    scenario = CallScenario(
        name="chained-allowed-call", calling_number=ALLOWED_CALLER, called_number=CALLED_NUMBER
    )
    trunk_call_id = pair.place_call(scenario)
    outcome = pair.outcome_for(trunk_call_id)
    assert outcome is not None

    finished = pair.run_until(lambda: (pair.outcome_for(trunk_call_id) or outcome).released)
    outcome = pair.outcome_for(trunk_call_id) or outcome

    second_call_id = inter_as_call_id(pair)
    as1_trace = pair.as_stack.tracer.trace_for(trunk_call_id)
    as2_trace = pair.second_as.tracer.trace_for(second_call_id)
    with capsys.disabled():
        print("AS-1 (anti-fraud), keyed on the S-CSCF Call-ID")
        print(render_trace(as1_trace))
        print("AS-2 (number translation), keyed on the Call-ID AS-1 sent")
        print(render_trace(as2_trace))

    assert finished, f"the chained call {trunk_call_id} did not finish within the timeout"
    assert outcome.status == 200, f"the caller saw {outcome.status} instead of 200 OK"
    assert outcome.released is True

    # The two per-instance traces are keyed on **different** Call-IDs: AS-2 saw the value
    # AS-1 derived, not the S-CSCF's (REQ-NF-016, LLD section 10.2). Without the per-leg
    # derivation the two traces would collapse onto one key and this would fail.
    assert second_call_id == outbound_call_id(trunk_call_id)
    assert second_call_id != trunk_call_id, (
        "AS-1 reused the trunk Call-ID on its outbound leg, so the chain has one key"
    )

    # Both instances drove the one call through its complete sequence.
    as1_methods = [event.method for event in as1_trace.events]
    as2_methods = [event.method for event in as2_trace.events]
    for method in ("INVITE", "180", "200", "BYE"):
        assert method in as1_methods, f"AS-1's trace is missing {method}"
        assert method in as2_methods, f"AS-2's trace is missing {method}"

    # The far end of the chain saw AS-2's translated number.
    invites = list(pair.mock.uas.received_invites)
    assert invites, "no INVITE reached the core side of the mock"
    assert invites[0].called_number == TRANSLATED_NUMBER

    # Per-instance observability: AS-1 recorded the verdict, AS-2 the matched rule, each
    # under the Call-ID it saw on its own trunk leg (REQ-F-028).
    assert verdict_of(as1_trace) == "allow", "AS-1 did not record its allow verdict"
    assert matched_rule(as2_trace) == MATCHED_RULE, (
        f"AS-2 did not record the matched rule {MATCHED_RULE}"
    )


def test_a_rejected_call_ends_with_608_at_as1_and_reaches_nothing_else(
    chained_pair_factory, capsys: pytest.CaptureFixture[str]
) -> None:
    """A blocked caller is answered ``608`` by AS-1; AS-2 and the core see nothing.

    The reject branch of the chain end to end (REQ-F-027): the short-circuit is asserted as
    an absence at AS-2 and the core, taken as a delta so the assertion is on this call.
    """
    pair = chained_pair_factory()
    as2_before = len(pair.second_as.tracer.known_call_ids())
    core_before = len(pair.mock.uas.received_invites)

    scenario = CallScenario(
        name="chained-rejected-call",
        calling_number=BLOCKED_CALLER,
        called_number=CALLED_NUMBER,
        expect_status=608,
    )
    call_id = pair.place_call(scenario)
    outcome = pair.outcome_for(call_id)
    assert outcome is not None

    finished = pair.run_until(lambda: (pair.outcome_for(call_id) or outcome).released)
    outcome = pair.outcome_for(call_id) or outcome
    trace = pair.as_stack.tracer.trace_for(call_id)
    with capsys.disabled():
        print("AS-1 (anti-fraud), the whole call")
        print(render_trace(trace))

    assert finished, f"the rejected call {call_id} did not finish within the timeout"
    assert outcome.status == 608, f"the caller saw {outcome.status} instead of 608"
    assert outcome.released is True

    methods = [event.method for event in trace.events]
    assert "608" in methods, "the 608 response is not in AS-1's Call-ID keyed trace"
    assert "BYE" not in methods, "a rejected call is never established"
    assert verdict_of(trace) == "reject", "AS-1 did not record its reject verdict"

    # No second leg was originated, so AS-2 and the core each saw nothing new.
    assert len(pair.second_as.tracer.known_call_ids()) - as2_before == 0, (
        "a rejected call must not create any call state at AS-2"
    )
    assert len(pair.mock.uas.received_invites) - core_before == 0, (
        "a rejected call must not originate an INVITE towards the core"
    )
