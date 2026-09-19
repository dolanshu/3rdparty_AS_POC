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

"""Integration tests for the anti-fraud screening path on localhost UDP.

What is exercised here, on the wire and with ephemeral ports (never 5060 or 5062):

- the **reject path is UAS-only**: the caller sees ``608`` and the core side of the mock
  receives **no INVITE at all** — the absence of the second leg is the assertion, not just
  the status code (REQ-F-021);
- the **allow path** completes and the relayed INVITE adds no header, with the Request-URI
  user part and the SDP body unchanged (REQ-F-017, REQ-F-019);
- the trunk peer allowlist is enforced before any call state exists (``AGENT.md`` §9);
- a caller that never declared ``sip.608`` is still answered ``608``, and that the
  announcement obligation was therefore unmet is recorded (ADR-0007 decision 5);
- the call-rate window and the reputation ledger reject through the real controller, with an
  injected clock so nothing waits (REQ-F-018, REQ-NF-011);
- a screening-data edit is picked up by the loop-owned reload, and a broken edit keeps the
  previous data (ADR-0004 fail-safe rule);
- stopping the process cancels every timer it armed (P8a lesson 5, REQ-F-016).

Covers ACC-P8-001 (REQ-F-016, REQ-F-021), ACC-P8-002 (REQ-F-017, REQ-F-019),
ACC-P8-003 (REQ-F-018) and ACC-P8-005 (REQ-F-024).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from anti_fraud_as.caller_state import CallerStateStore, WindowPolicy
from as_app.sip_adapter import PASSTHROUGH_HEADERS, TRANSACTION_TIMER_NAMES, outbound_call_id
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.integration

#: A caller the shipped screening data blocks (first entry of the block list).
BLOCKED_CALLER = "+8613400000001"

#: A caller the shipped screening data does not list, with a healthy window and score.
ALLOWED_CALLER = "+86216180001"

#: A second loopback address the anti-fraud trunk has not been told to trust.
FOREIGN_TRUNK_ADDRESS = "127.0.0.2"

_HEADER_LINE = re.compile(r"^([A-Za-z0-9.\-]+):[ \t]*(.*)$")

#: Screening data with thresholds that make one call enough to trip each signal. A long
#: half-life keeps the decay out of the way while the window is being exercised.
_TIGHT_SCREENING = """\
version: 1
name: integration-tight
window:
  seconds: 60
  max_calls: 1
reputation:
  half_life_seconds: 3600
  default_score: 100.0
  reject_below: 90.0
  reject_penalty: 20.0
  max_tracked_callers: 100
block_list: []
allow_list: []
"""


# ---------------------------------------------------------------------------
# Small parsers, so the assertions are on real bytes
# ---------------------------------------------------------------------------


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


def request_uri_of(message: str) -> str:
    """Return the Request-URI of a raw SIP request.

    Args:
        message: A complete SIP request.

    Returns:
        The Request-URI.
    """
    return message.split("\r\n", 1)[0].split(" ")[1]


def user_part_of(request_uri: str) -> str:
    """Return the user part of a SIP URI.

    Args:
        request_uri: A ``sip:`` URI.

    Returns:
        The part between ``sip:`` and ``@``.
    """
    return request_uri.split("sip:", 1)[1].split("@", 1)[0]


def invites_of(recorder: Any, call_id: str, direction: str) -> list[Any]:
    """Return the INVITEs of one call recorded on one direction.

    Args:
        recorder: The AS-side ``SipMessageRecorder``.
        call_id: SIP Call-ID of the call.
        direction: ``in`` or ``out``.

    Returns:
        The matching recorded messages, in the order they were seen.
    """
    return [
        message
        for message in recorder.messages_for_any((call_id, outbound_call_id(call_id)))
        if message.direction == direction and message.text.startswith("INVITE ")
    ]


def verdict_attributes(stack: Any, call_id: str) -> dict[str, Any]:
    """Return the trace attributes of the verdict event of one call.

    Args:
        stack: The running anti-fraud stack.
        call_id: SIP Call-ID of the call.

    Returns:
        The verdict attributes, empty when the call has no verdict event.
    """
    for event in stack.tracer.trace_for(call_id).events:
        if event.method == "verdict":
            return dict(event.attributes)
    return {}


# ---------------------------------------------------------------------------
# Reject path: 608 on the trunk, no second leg
# ---------------------------------------------------------------------------


def test_a_block_listed_caller_is_answered_608_and_never_reaches_the_core(
    fraud_trunk_pair,
) -> None:
    """The reject is UAS-only: no INVITE is ever originated towards the core.

    Asserting the *absence* of the second leg is the point — a reject that quietly relayed
    the call first would still answer 608 to the caller, and would be a completely different
    item (REQ-F-021, P8 "Known collisions").
    """
    scenario = CallScenario(
        name="screening-reject",
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

    assert finished, f"call {call_id} did not finish within the timeout"
    assert outcome.status == 608, f"caller saw {outcome.status} instead of 608"
    assert outcome.released is True

    # The **full final response line** goes over the wire. ``SIP_PHRASES[608]`` is the only
    # reason the caller reads "Rejected" rather than a fallback phrase (LLD section 9.5), so
    # the phrase is asserted on the wire, not only against the constant table.
    response_lines = [
        message.text.split("\r\n", 1)[0]
        for message in fraud_trunk_pair.as_messages.messages_for_any(
            (call_id, outbound_call_id(call_id))
        )
        if message.direction == "out" and message.text.startswith("SIP/2.0 ")
    ]
    assert "SIP/2.0 608 Rejected" in response_lines, (
        f"the wire did not carry 'SIP/2.0 608 Rejected': {response_lines}"
    )

    assert not fraud_trunk_pair.mock.uas.received_invites, (
        "a rejected call must not originate an INVITE towards the core"
    )

    attributes = verdict_attributes(fraud_trunk_pair.as_stack, call_id)
    assert attributes["verdict"] == "reject"
    assert attributes["screen_source"] == "block_list"
    assert attributes["list_entry"] == "BL-0001"
    assert attributes["sip_608_declared"] is True

    methods = [event.method for event in fraud_trunk_pair.as_stack.tracer.trace_for(call_id).events]
    assert "608" in methods, "the 608 response is not in the Call-ID keyed trace"

    counters = fraud_trunk_pair.as_stack.metrics.snapshot()
    assert counters.counters["verdict.reject"] == 1
    assert counters.counters["screen.block_list"] == 1
    assert counters.errors_by_code["AS-FRAUD-001"] == 1
    assert counters.calls_by_disposition["rejected"] == 1

    # Positive control: the "the core saw nothing" assertion above is only meaningful if the
    # core-side observation channel works **in this same test**. An allowed call on the same
    # pair is relayed, so the recorder must then show exactly its INVITE — and nothing of the
    # rejected call. A dead recorder cannot make the absence above pass by accident.
    allowed_call_id = place_screening_call(
        fraud_trunk_pair, "screening-reject-control", ALLOWED_CALLER
    )
    received_call_ids = [invite.call_id for invite in fraud_trunk_pair.mock.uas.received_invites]
    assert received_call_ids == [outbound_call_id(allowed_call_id)], (
        f"the core-side recorder is not observing the relayed call: {received_call_ids}"
    )
    # The regression made explicit: the relayed leg carries its own dialog identity, derived
    # from the trunk Call-ID, so the core never sees the S-CSCF's value (REQ-NF-016, LLD
    # section 10.2). A controller that forgot the derivation would reuse the trunk value.
    assert outbound_call_id(allowed_call_id) != allowed_call_id


def test_a_caller_that_never_declared_sip_608_is_still_answered_608(fraud_trunk_pair) -> None:
    """The declaration selects no status code; it only says the announcement was not met.

    RFC 8688 section 3.4 forwards the 608 as the final response either way, so the AS must
    not branch on ``Feature-Caps``. The unmet obligation is recorded instead — that is the
    registered gap, made observable (ADR-0007 decision 5).
    """
    call_id = "no-feature-caps-0001@example.invalid"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind(("127.0.0.1", 0))
        client.settimeout(1.0)
        local_port = int(client.getsockname()[1])
        invite = (
            "INVITE sip:+8613800138000@127.0.0.1;user=phone SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{local_port};branch=z9hG4bKnofcaps0001;rport\r\n"
            "Max-Forwards: 70\r\n"
            f"From: <sip:{BLOCKED_CALLER}@127.0.0.1>;tag=no-feature-caps\r\n"
            "To: <sip:+8613800138000@127.0.0.1>\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 1 INVITE\r\n"
            f"Contact: <sip:127.0.0.1:{local_port}>\r\n"
            f"P-Asserted-Identity: <sip:{BLOCKED_CALLER}@ims.example.invalid>\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        ).encode()
        client.sendto(invite, ("127.0.0.1", fraud_trunk_pair.as_port))

        responses: list[bytes] = []
        fraud_trunk_pair.run_until(
            lambda: _drain_until_final(client, responses), timeout_seconds=3.0
        )

    finals = [data for data in responses if _status_of_response(data) >= 200]
    assert finals, f"the AS sent no final response, only {len(responses)} provisional datagram(s)"
    response_text = finals[0].decode(errors="replace")
    status_line = response_text.split("\r\n", 1)[0]
    # The full reason phrase is asserted, not only the code: ``SIP_PHRASES[608]`` is the only
    # thing that puts "Rejected" on the wire (LLD section 9.5).
    assert status_line == "SIP/2.0 608 Rejected", status_line

    # RFC 8688 sections 3.1 and 6: the rejection carries no Call-Info, and with no body it
    # carries no Content-Type either - the AS is signalling-only and plays no announcement
    # (REQ-F-019, ADR-0006).
    reply_headers = headers_of(response_text)
    assert "call-info" not in reply_headers, "the 608 must not carry a Call-Info header"
    assert "content-type" not in reply_headers, "the 608 must not carry a body"

    attributes = verdict_attributes(fraud_trunk_pair.as_stack, call_id)
    assert attributes["verdict"] == "reject"
    assert attributes["sip_608_declared"] is False

    counters = fraud_trunk_pair.as_stack.metrics.snapshot()
    assert counters.counters["reject.sip_608_undeclared"] == 1


def test_a_reject_from_the_allow_list_is_not_rejected(fraud_trunk_pair) -> None:
    """An exempt caller is allowed even though the screening runs on every call."""
    scenario = CallScenario(
        name="screening-allow-list",
        calling_number="+86216180000",
        called_number="+8613800138000",
    )
    call_id = fraud_trunk_pair.place_call(scenario)
    outcome = fraud_trunk_pair.outcome_for(call_id)
    assert outcome is not None
    fraud_trunk_pair.run_until(lambda: (fraud_trunk_pair.outcome_for(call_id) or outcome).released)
    outcome = fraud_trunk_pair.outcome_for(call_id) or outcome

    attributes = verdict_attributes(fraud_trunk_pair.as_stack, call_id)

    assert outcome.status == 200
    assert attributes["verdict"] == "allow"
    assert attributes["screen_source"] == "allow_list"
    assert attributes["list_entry"] == "AL-0001"


# ---------------------------------------------------------------------------
# Allow path: relayed, with nothing added
# ---------------------------------------------------------------------------


def test_an_allowed_call_is_relayed_with_no_added_header(fraud_trunk_pair) -> None:
    """The relayed INVITE keeps the Request-URI user part, the SDP body and the headers.

    "Relayed" is read at the B2BUA boundary: what crosses unchanged is the Request-URI and
    the **pass-through header set**, and nothing is added (REQ-F-017, REQ-F-019).
    ``Feature-Caps`` is not in that set, so the declaration does not cross the AS — a
    registered gap, asserted here so it cannot drift silently.
    """
    scenario = CallScenario(
        name="screening-relay",
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

    assert finished, f"call {call_id} did not finish within the timeout"
    assert outcome.status == 200, f"caller saw {outcome.status} instead of 200 OK"
    assert fraud_trunk_pair.mock.uas.received_invites, "no INVITE reached the core side"

    inbound = invites_of(fraud_trunk_pair.as_messages, call_id, "in")
    outbound = invites_of(fraud_trunk_pair.as_messages, call_id, "out")
    assert len(inbound) == 1, f"expected one inbound INVITE, got {len(inbound)}"
    assert len(outbound) == 1, f"expected one outbound INVITE, got {len(outbound)}"

    sent = headers_of(inbound[0].text)
    relayed = headers_of(outbound[0].text)

    # The called number is never rewritten on this path.
    assert user_part_of(request_uri_of(outbound[0].text)) == "+8613800138000"
    assert user_part_of(request_uri_of(inbound[0].text)) == "+8613800138000"
    # The SDP body crosses untouched.
    assert body_of(outbound[0].text) == body_of(inbound[0].text)
    # Every pass-through header the trunk carried arrives unchanged.
    exercised = [name for name in PASSTHROUGH_HEADERS if name in sent]
    assert "p-asserted-identity" in exercised
    for name in exercised:
        assert relayed.get(name) == sent[name], (
            f"header {name} changed across the relay: {sent[name]!r} -> {relayed.get(name)!r}"
        )
    # No header is added, and in particular no Call-Info accompanies an accepted call.
    assert set(relayed) <= set(sent) | {"content-length"}, (
        f"the relay added headers: {sorted(set(relayed) - set(sent))}"
    )
    assert "call-info" not in relayed
    # Registered gap: the sip.608 declaration does not survive the relay.
    assert "feature-caps" in sent
    assert "feature-caps" not in relayed

    attributes = verdict_attributes(fraud_trunk_pair.as_stack, call_id)
    assert attributes["verdict"] == "allow"
    assert attributes["identity_present"] is True
    counters = fraud_trunk_pair.as_stack.metrics.snapshot()
    assert counters.counters["verdict.allow"] == 1


def test_an_invite_without_a_calling_identity_is_allowed(fraud_trunk_pair) -> None:
    """No ``P-Asserted-Identity`` means no signal to screen, so the call is relayed.

    The engine's fail-open branch is unit-tested; this drives it through the real wiring.
    ``FraudCallController.apply_call_policy`` reads no calling party, sets
    ``identity_present=false`` and ``screen_source=none``, and relays the INVITE instead of
    rejecting it (ADR-0007 decision 7, REQ-F-018).
    """
    call_id = "no-identity-0001@example.invalid"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind(("127.0.0.1", 0))
        local_port = int(client.getsockname()[1])
        invite = (
            "INVITE sip:+8613800138000@127.0.0.1;user=phone SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{local_port};branch=z9hG4bKnoidentity01;rport\r\n"
            "Max-Forwards: 70\r\n"
            "From: <sip:+8613500000456@127.0.0.1>;tag=no-identity\r\n"
            "To: <sip:+8613800138000@127.0.0.1>\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 1 INVITE\r\n"
            f"Contact: <sip:127.0.0.1:{local_port}>\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        ).encode()
        client.sendto(invite, ("127.0.0.1", fraud_trunk_pair.as_port))

        # Drive until the AS has relayed the INVITE: the relay is the observable proof that
        # the verdict was *allow*, and unlike a datagram drain it does not block the loop.
        relayed = fraud_trunk_pair.run_until(
            lambda: bool(invites_of(fraud_trunk_pair.as_messages, call_id, "out")),
            timeout_seconds=5.0,
        )

    assert relayed, "the AS did not relay an INVITE that carried no calling identity"

    attributes = verdict_attributes(fraud_trunk_pair.as_stack, call_id)
    assert attributes["verdict"] == "allow"
    assert attributes["identity_present"] is False
    assert attributes["screen_source"] == "none"

    methods = [event.method for event in fraud_trunk_pair.as_stack.tracer.trace_for(call_id).events]
    assert "608" not in methods, "the fail-open path must not reject"

    # The call was relayed: the fail-open path is an allow, not a silent drop.
    assert fraud_trunk_pair.mock.uas.received_invites, "the allowed call was not relayed"
    # The relayed leg derives its own Call-ID from the trunk value; the core sees the
    # ``-b2b_1`` form, never the trunk identity (REQ-NF-016, LLD section 10.2).
    relayed_call_id = fraud_trunk_pair.mock.uas.received_invites[0].call_id
    assert relayed_call_id == outbound_call_id(call_id)
    assert relayed_call_id != call_id


# ---------------------------------------------------------------------------
# Trunk peer allowlist
# ---------------------------------------------------------------------------


def test_a_request_from_an_unlisted_source_is_rejected(fraud_trunk_pair) -> None:
    """The second trunk is untrusted for the same reason as the first (AGENT.md §9)."""
    call_id = "fraud-peer-check-0001@example.invalid"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind((FOREIGN_TRUNK_ADDRESS, 0))
        client.settimeout(1.0)
        local_port = int(client.getsockname()[1])
        invite = (
            "INVITE sip:+8613800138000@127.0.0.1;user=phone SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {FOREIGN_TRUNK_ADDRESS}:{local_port}"
            ";branch=z9hG4bKfraudpeer0001;rport\r\n"
            "Max-Forwards: 70\r\n"
            f"From: <sip:{ALLOWED_CALLER}@127.0.0.1>;tag=fraud-peer-check\r\n"
            "To: <sip:+8613800138000@127.0.0.1>\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 1 INVITE\r\n"
            f"Contact: <sip:{FOREIGN_TRUNK_ADDRESS}:{local_port}>\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        ).encode()
        client.sendto(invite, ("127.0.0.1", fraud_trunk_pair.as_port))

        responses: list[bytes] = []
        fraud_trunk_pair.run_until(lambda: _drain(client, responses), timeout_seconds=3.0)

    assert responses, "the anti-fraud AS did not answer the unlisted source"
    status_line = responses[0].decode(errors="replace").split("\r\n", 1)[0]
    assert status_line.startswith("SIP/2.0 403"), status_line

    counters = fraud_trunk_pair.as_stack.metrics.snapshot()
    assert counters.errors_by_code.get("AS-PEER-001") == 1
    # No call state is created for an untrusted source.
    assert fraud_trunk_pair.as_stack.call_map.controllers == []


# ---------------------------------------------------------------------------
# The window and the reputation, through the real controller
# ---------------------------------------------------------------------------


def test_the_window_and_then_reputation_reject_through_the_real_controller(
    fraud_pair_factory, tmp_path: Path
) -> None:
    """A burst is rejected by the window; the caller it penalised is later rejected on score.

    The clock is injected into the process-level store, so this exercises the real verdict
    seam without waiting for a minute to pass (REQ-NF-011). The sequence is deliberate:

    1. first call is inside the window and the score is whole — allowed;
    2. second call is one past ``max_calls`` — rejected by the **window**, and the rejection
       costs the caller ``reject_penalty`` points;
    3. after the window has moved on, the count is back to one, so only the **penalty** can
       reject — and it does.

    Step 3 is what proves the penalty is not a bookkeeping detail: it changes a later
    verdict.
    """
    screening_path = tmp_path / "tight.yaml"
    screening_path.write_text(_TIGHT_SCREENING, encoding="utf-8")
    clock = _FakeClock()
    policy = WindowPolicy(
        window_seconds=60.0,
        max_calls=1,
        half_life_seconds=3600.0,
        default_score=100.0,
        reject_penalty=20.0,
        max_tracked_callers=100,
    )
    pair = fraud_pair_factory(
        screening_path=screening_path,
        caller_state=CallerStateStore(policy, clock=clock),
    )
    caller = "+8613500000009"

    outcomes = []
    for index in range(3):
        scenario = CallScenario(
            name=f"tight-{index}",
            calling_number=caller,
            called_number="+8613800138000",
            expect_status=200 if index == 0 else 608,
        )
        call_id = pair.place_call(scenario)
        outcome = pair.outcome_for(call_id)
        assert outcome is not None
        pair.run_until(lambda cid=call_id, out=outcome: (pair.outcome_for(cid) or out).released)
        outcome = pair.outcome_for(call_id) or outcome
        outcomes.append(outcome)
        if index == 1:
            # Step the injected clock past the window so the next call is not a burst.
            clock.advance(120.0)

    assert [outcome.status for outcome in outcomes] == [200, 608, 608]

    counters = pair.as_stack.metrics.snapshot()
    assert counters.counters["screen.rate_window"] == 1
    assert counters.counters["screen.reputation"] == 1
    assert counters.errors_by_code["AS-FRAUD-002"] == 1
    assert counters.errors_by_code["AS-FRAUD-003"] == 1
    assert counters.counters["verdict.allow"] == 1
    assert counters.counters["verdict.reject"] == 2


# ---------------------------------------------------------------------------
# Screening-data reload, driven by the loop
# ---------------------------------------------------------------------------


def test_a_reloaded_file_activates_a_new_block_entry(
    fraud_trunk_pair, screening_file: Path
) -> None:
    """An operator edit takes effect on the polling tick, without a restart.

    The reload is applied by the loop-owned poller, which re-reads the file **and**
    re-applies the window and reputation parameters to the process-level state — so this
    asserts the effect on a real verdict, not just that the document object changed.
    """
    new_caller = "+8613500000009"
    assert new_caller not in screening_file.read_text(encoding="utf-8")

    edited = screening_file.read_text(encoding="utf-8").replace(
        "block_list:\n",
        f'block_list:\n  - number: "{new_caller}"\n    reason: added by the test\n',
    )
    screening_file.write_text(edited, encoding="utf-8")

    fraud_trunk_pair.as_stack._poll_screening_reload()  # noqa: SLF001 - the loop callback
    assert fraud_trunk_pair.as_stack.screening_data.current.match(new_caller).blocked_by

    call_id = place_screening_call(fraud_trunk_pair, "reloaded-block", new_caller)
    outcome = fraud_trunk_pair.outcome_for(call_id)

    assert outcome is not None
    assert outcome.status == 608
    assert verdict_attributes(fraud_trunk_pair.as_stack, call_id)["screen_source"] == "block_list"


def test_a_reload_reapplies_the_window_and_reputation_parameters(
    fraud_trunk_pair, screening_file: Path
) -> None:
    """The loop callback hands the reloaded parameters to the process-level store.

    ``_poll_screening_reload`` re-reads the file **and** calls
    ``CallerStateStore.reconfigure``, which is what makes a ``window``/``reputation`` edit take
    effect without a restart. The numbers below differ from the shipped ones, so a callback
    that reloaded the document but forgot the store would leave the old policy in force and
    fail here — which is exactly the wiring the docstring promises.
    """
    store = fraud_trunk_pair.as_stack.caller_state
    active = store.policy

    edited = (
        screening_file.read_text(encoding="utf-8")
        .replace("max_calls: 5", "max_calls: 2")
        .replace("reject_penalty: 40.0", "reject_penalty: 5.0")
        .replace("default_score: 100.0", "default_score: 60.0")
    )
    screening_file.write_text(edited, encoding="utf-8")

    fraud_trunk_pair.as_stack._poll_screening_reload()  # noqa: SLF001 - the loop callback

    reloaded = store.policy
    assert reloaded != active, "the reload did not change the policy in force"
    assert reloaded == fraud_trunk_pair.as_stack.screening_data.current.policy
    assert reloaded.max_calls == 2
    assert reloaded.reject_penalty == 5.0
    # The store enforces the new parameters: an unseen caller now starts at the new default.
    assert store.observe("+8613500000123").effective_reputation == 60.0


def test_a_broken_edit_keeps_the_previous_screening_data(
    fraud_trunk_pair, screening_file: Path
) -> None:
    """A bad edit is contained: the previous data stays active (ADR-0004 fail-safe rule).

    The poller swallows the error into ``AS-FRAUD-005`` (it runs inside the event loop and
    must not raise), and the call path notices nothing: the caller that was blocked is still
    blocked, and the caller that was allowed is still allowed.
    """
    screening_file.write_text("window: [unclosed\n", encoding="utf-8")

    # The loop-owned callback must not raise: an exception there would break the event loop.
    fraud_trunk_pair.as_stack._poll_screening_reload()  # noqa: SLF001 - the loop callback

    blocked_id = place_screening_call(fraud_trunk_pair, "after-broken-edit", BLOCKED_CALLER)
    allowed_id = place_screening_call(fraud_trunk_pair, "after-broken-edit-allow", ALLOWED_CALLER)
    blocked = fraud_trunk_pair.outcome_for(blocked_id)
    allowed = fraud_trunk_pair.outcome_for(allowed_id)

    assert blocked is not None and blocked.status == 608
    assert allowed is not None and allowed.status == 200


def place_screening_call(pair: Any, name: str, calling_number: str) -> str:
    """Place one call, drive the loop until it is released, and return its Call-ID.

    Args:
        pair: The bound anti-fraud pair.
        name: Scenario name, used in logs and traces.
        calling_number: Calling party to send as ``P-Asserted-Identity``.

    Returns:
        The SIP Call-ID of the call.
    """
    scenario = CallScenario(
        name=name,
        calling_number=calling_number,
        called_number="+8613800138000",
    )
    call_id = pair.place_call(scenario)
    outcome = pair.outcome_for(call_id)
    assert outcome is not None
    pair.run_until(lambda cid=call_id, out=outcome: (pair.outcome_for(cid) or out).released)
    return call_id


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_stopping_the_process_leaves_no_timer_armed(fraud_pair_factory, free_udp_port: int) -> None:
    """Nothing the anti-fraud process armed outlives its stop path (P8a lesson 5).

    The next hop is an unbound port, so the relayed INVITE keeps retransmitting and the
    controller's no-answer timer stays armed — exactly the state that used to leave a timer
    firing into a shut-down transaction manager. ``stop()`` has to cancel both.
    """
    from sippy.Core.EventDispatcher import ED2
    from sippy.Time.Timeout import Timeout

    pair = fraud_pair_factory(peer_port=free_udp_port)
    stack = pair.as_stack
    scenario = CallScenario(
        name="pending-relay",
        calling_number=ALLOWED_CALLER,
        called_number="+8613800138000",
        expect_status=200,
    )
    call_id = pair.place_call(scenario)

    relayed = pair.run_until(
        lambda: bool(invites_of(pair.as_messages, call_id, "out")), timeout_seconds=5.0
    )
    assert relayed, "the AS never relayed the INVITE towards the unreachable peer"

    manager = stack.transaction_manager
    assert manager is not None
    # Premise: without it the assertions below would pass even if nothing were cancelled.
    assert _armed_transaction_timers(manager), "the relayed INVITE left no pending retransmission"
    controller = stack.call_map.controllers[0]
    assert controller._no_answer_timer is not None, "the no-answer timer was never armed"  # noqa: SLF001

    stack.stop()

    assert controller._no_answer_timer is None, (  # noqa: SLF001
        "the controller-owned no-answer timer was not cancelled on the stop path"
    )
    assert not _armed_loop_timers(manager), "a timer of the stopped manager is still scheduled"

    # Drive the shared loop past the instants at which a surviving timer would have fired.
    settle_timer = Timeout(lambda: ED2.breakLoop(), 1.5, 1)
    try:
        ED2.loop(timeout=4.0)
    finally:
        settle_timer.cancel()
    assert not _armed_loop_timers(manager), (
        "a timer was re-armed after the transaction manager had been shut down"
    )


def test_the_process_serves_health_and_exits_zero_on_sigterm(
    repo_root: Path, screening_file: Path, tmp_path: Path
) -> None:
    """The second AS owns its lifecycle: self-check, health, graceful stop (REQ-F-016).

    Run as a real process, because the point is that the entry point and its stop path work
    outside the test process — and the port it reports is the one it actually holds.
    """
    sip_port = free_udp_port_for_tests()
    # The internal API is HTTP over TCP, so its port is reserved with a TCP probe. Reserving
    # it by probing UDP guarantees nothing about TCP (see the gap registered by P8a,
    # docs/phase2-plan.md section 7 item 7).
    api_port = _free_tcp_port()
    environment = dict(os.environ)
    environment.update(
        {
            "FRAUD_SIP_LISTEN_ADDRESS": "127.0.0.1",
            "FRAUD_SIP_LISTEN_PORT": str(sip_port),
            "FRAUD_SBC_PEER_ADDRESS": "127.0.0.1",
            "FRAUD_SBC_PEER_PORT": str(free_udp_port_for_tests()),
            "FRAUD_ALLOWED_PEERS": "127.0.0.1",
            "FRAUD_SCREENING_FILE": str(screening_file),
            "FRAUD_INTERNAL_API_ADDRESS": "127.0.0.1",
            "FRAUD_INTERNAL_API_PORT": str(api_port),
            "LOG_LEVEL": "INFO",
            "LOG_STRUCTURED": "true",
            "LOG_PAYLOADS": "false",
        }
    )
    log_path = tmp_path / "anti_fraud_as.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "anti_fraud_as.main"],
            cwd=repo_root,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            assert _wait_for_health(api_port), "the anti-fraud health endpoint never came up"
            with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/healthz", timeout=5) as page:
                health = json.loads(page.read().decode())
            assert health["status"] == "ok"
            assert health["instance"] == "anti-fraud"
            assert health["screening_data_loaded"] is True
            assert health["rule_set_loaded"] is True

            with urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/api/v1/screening", timeout=5
            ) as page:
                screening = json.loads(page.read().decode())
            assert screening["name"] == "sample-office-screening"
            assert screening["block_list"]

            # The verdict is observable off the wire (REQ-F-024): the same two surfaces the
            # console reads must answer on the live process, not only through the payload
            # builders.
            with urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/api/v1/metrics", timeout=5
            ) as page:
                metrics = json.loads(page.read().decode())
            assert metrics["calls_total"] == 0
            assert metrics["counters"] == {}
            assert "errors_by_code" in metrics

            with urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/api/v1/traces", timeout=5
            ) as page:
                traces = json.loads(page.read().decode())
            assert traces["calls"] == []

            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=15) == 0, "SIGTERM did not shut the process down cleanly"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    log_text = log_path.read_text(encoding="utf-8")
    assert "anti-fraud application server starting" in log_text
    assert "startup self-check passed" in log_text
    assert "shutdown complete" in log_text
    assert '"reason": "signal SIGTERM"' in log_text


def test_the_running_process_reloads_the_screening_file_on_its_own_timer(
    repo_root: Path, screening_file: Path, tmp_path: Path
) -> None:
    """The reload timer is armed by ``run()``, not only reachable by calling the callback.

    Both in-process reload tests call ``_poll_screening_reload`` themselves, so a ``run()``
    that never armed the loop-owned timer would leave them green. This observes a **real
    process**: the file is edited while it runs and the change becomes visible through the
    internal API without anyone calling the callback (the ADR-0004 pattern, REQ-F-016).
    """
    sip_port = free_udp_port_for_tests()
    api_port = _free_tcp_port()
    reloaded_caller = "+8613500000777"
    original = screening_file.read_text(encoding="utf-8")
    assert reloaded_caller not in original

    environment = dict(os.environ)
    environment.update(
        {
            "FRAUD_SIP_LISTEN_ADDRESS": "127.0.0.1",
            "FRAUD_SIP_LISTEN_PORT": str(sip_port),
            "FRAUD_SBC_PEER_ADDRESS": "127.0.0.1",
            "FRAUD_SBC_PEER_PORT": str(free_udp_port_for_tests()),
            "FRAUD_ALLOWED_PEERS": "127.0.0.1",
            "FRAUD_SCREENING_FILE": str(screening_file),
            "FRAUD_INTERNAL_API_ADDRESS": "127.0.0.1",
            "FRAUD_INTERNAL_API_PORT": str(api_port),
            "LOG_LEVEL": "INFO",
            "LOG_STRUCTURED": "true",
            "LOG_PAYLOADS": "false",
        }
    )
    log_path = tmp_path / "anti_fraud_as_reload.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "anti_fraud_as.main"],
            cwd=repo_root,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            assert _wait_for_health(api_port), "the anti-fraud health endpoint never came up"
            assert not _block_list_contains(api_port, reloaded_caller), (
                "the caller under test is already in the shipped block list"
            )

            screening_file.write_text(
                original.replace(
                    "block_list:\n",
                    f'block_list:\n  - number: "{reloaded_caller}"\n'
                    "    reason: added while running\n",
                ),
                encoding="utf-8",
            )

            assert _wait_for_block_entry(api_port, reloaded_caller), (
                "the running process never picked up the edited screening file: the "
                "loop-owned reload timer was not armed by run()"
            )
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """A monotonic clock a test advances by hand."""

    def __init__(self, now: float = 1000.0) -> None:
        """Create the clock at a fixed instant.

        Args:
            now: The instant to start at.
        """
        self.now = now

    def __call__(self) -> float:
        """Return the current instant.

        Returns:
            The instant the clock reads.
        """
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        Args:
            seconds: How far to move it.
        """
        self.now += seconds


def free_udp_port_for_tests() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _free_tcp_port() -> int:
    """Reserve a free TCP port on loopback.

    The internal API is HTTP over TCP, so a UDP probe would guarantee nothing about the
    port it is given. This is the same helper ``tests/integration/test_console.py`` uses.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _drain(client: socket.socket, responses: list[bytes]) -> bool:
    """Read pending datagrams from a socket into a list.

    Args:
        client: The socket to read from.
        responses: List the datagrams are appended to.

    Returns:
        ``True`` when at least one datagram has been collected.
    """
    try:
        data, _ = client.recvfrom(65535)
    except (TimeoutError, BlockingIOError):
        return bool(responses)
    responses.append(data)
    return True


def _drain_until_final(client: socket.socket, responses: list[bytes]) -> bool:
    """Drain datagrams until a final SIP response has been collected.

    An INVITE that reaches the screening seam is answered with ``100 Trying`` before the
    verdict, so a test that stopped at the first datagram would assert on the provisional
    response (RFC 3261 section 17.2.1).

    Args:
        client: The socket to read from.
        responses: List the datagrams are appended to.

    Returns:
        ``True`` once a response with a status of 200 or above has been seen.
    """
    _drain(client, responses)
    return any(_status_of_response(data) >= 200 for data in responses)


def _status_of_response(data: bytes) -> int:
    """Return the status code of a raw SIP response.

    Args:
        data: A datagram that is expected to be a SIP response.

    Returns:
        The status code, or ``0`` when the datagram does not start with a status line.
    """
    line = data.decode(errors="replace").split("\r\n", 1)[0]
    if not line.startswith("SIP/2.0 "):
        return 0
    try:
        return int(line.split(" ", 2)[1])
    except (IndexError, ValueError):
        return 0


def _wait_for_health(api_port: int, timeout_seconds: float = 15.0) -> bool:
    """Poll a health endpoint until it answers.

    A connection error means the process is still starting up, so the poll keeps waiting. A
    malformed HTTP response means something else is already listening on the port: that is a
    different failure and is raised rather than mistaken for "not up yet".

    Args:
        api_port: TCP port of the internal API.
        timeout_seconds: How long to keep polling.

    Returns:
        ``True`` when the endpoint answered, ``False`` on timeout.

    Raises:
        RuntimeError: When a non-HTTP listener occupies the port.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/healthz", timeout=1):
                return True
        except OSError:
            # Nothing is listening yet: the process is still coming up.
            time.sleep(0.1)
        except http.client.HTTPException as exc:
            raise RuntimeError(
                f"something is listening on 127.0.0.1:{api_port} but it is not the "
                f"anti-fraud internal API (malformed HTTP response: {exc!r})"
            ) from exc
    return False


def _screening_document(api_port: int) -> dict[str, Any]:
    """Fetch the screening document from a running internal API.

    Args:
        api_port: TCP port of the internal API.

    Returns:
        The decoded ``/api/v1/screening`` document.
    """
    with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/api/v1/screening", timeout=5) as page:
        return json.loads(page.read().decode())


def _block_list_contains(api_port: int, value: str) -> bool:
    """Tell whether a running process currently blocks a number.

    Args:
        api_port: TCP port of the internal API.
        value: The number to look for.

    Returns:
        ``True`` when the active block list carries the value.
    """
    return any(entry["value"] == value for entry in _screening_document(api_port)["block_list"])


def _wait_for_block_entry(api_port: int, value: str, timeout_seconds: float = 15.0) -> bool:
    """Poll a running process until a number appears in its block list.

    Args:
        api_port: TCP port of the internal API.
        value: The number to wait for.
        timeout_seconds: How long to keep polling.

    Returns:
        ``True`` when the entry became visible, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if _block_list_contains(api_port, value):
                return True
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.2)
    return False


def _armed_transaction_timers(manager: Any) -> list[Any]:
    """Return the per-transaction timers still armed on a transaction manager.

    Args:
        manager: A sippy ``SipTransactionManager``.

    Returns:
        One entry per transaction timer that has neither fired nor been cancelled. ``ED2``
        nulls the callback of a timer once it has run, which is how a cancelled or already
        fired timer is told apart from a pending one.
    """
    armed: list[Any] = []
    for table_name in ("tclient", "tserver"):
        transactions = getattr(manager, table_name, None) or {}
        for transaction in transactions.values():
            for timer_name in TRANSACTION_TIMER_NAMES:
                timer = getattr(transaction, timer_name, None)
                if timer is not None and getattr(timer, "cb_func", None) is not None:
                    armed.append(timer)
    return armed


def _armed_loop_timers(manager: Any) -> list[Any]:
    """Return the shared-loop timers still owned by one transaction manager.

    Args:
        manager: A sippy ``SipTransactionManager``.

    Returns:
        The ``ED2`` listeners whose callback still belongs to that manager. This is the
        authoritative view: sippy's own shutdown clears its registries, so only the event
        loop can tell whether anything of the manager is still scheduled.
    """
    from sippy.Core.EventDispatcher import ED2

    return [
        listener
        for listener in ED2.tlisteners
        if listener.cb_func is not None and getattr(listener.cb_func, "__self__", None) is manager
    ]
