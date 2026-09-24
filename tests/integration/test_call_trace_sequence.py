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

"""P15-A integration: TraceRecorder REST payload for sequence diagram (REQ-F-056)."""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import quote

import pytest

from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.integration


def _fetch_trace(api_port: int, call_id: str) -> dict:
    encoded = quote(call_id, safe="")
    url = f"http://127.0.0.1:{api_port}/api/v1/traces/{encoded}"
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode())


def test_completed_call_trace_has_invite_and_200_events(trunk_pair) -> None:
    """REST trace lists trunk INVITE, routing decision, and next-hop 200 for a completed call."""
    trunk_pair.as_stack.start_internal_api()
    api_port = int(trunk_pair.as_stack.settings.internal_api_port)

    scenario = CallScenario(
        name="trace-sequence",
        calling_number="+86216180001",
        called_number="+8613800138000",
        ring_seconds=0.05,
        talk_seconds=0.05,
    )
    call_id = str(trunk_pair.place_call(scenario))
    finished = trunk_pair.run_until(
        lambda: (
            (outcome := trunk_pair.outcome_for(call_id)) is not None and outcome.released
        ),
        timeout_seconds=15.0,
    )
    assert finished, "call did not complete"

    payload = _fetch_trace(api_port, call_id)
    events = payload.get("events") or []
    assert payload.get("call_id") == call_id
    assert events, "expected non-empty trace"

    methods = [event.get("method") for event in events]
    legs = [(event.get("attributes") or {}).get("leg") for event in events]
    directions = [event.get("direction") for event in events]

    assert "INVITE" in methods
    assert any(m == "200" for m in methods)
    assert any(d == "internal" for d in directions)
    assert "trunk" in legs and "next_hop" in legs

    timestamps = [event.get("timestamp") for event in events]
    assert timestamps == sorted(timestamps), "events should stay time-ordered"
