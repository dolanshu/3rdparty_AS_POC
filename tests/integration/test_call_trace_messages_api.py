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

"""P15-B integration: verbatim SIP messages REST API (REQ-F-057)."""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import quote

import pytest

from as_app.sip_adapter import outbound_call_id
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.integration


def _fetch_messages(api_port: int, call_id: str) -> dict:
    encoded = quote(call_id, safe="")
    url = f"http://127.0.0.1:{api_port}/api/v1/traces/{encoded}/messages"
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode())


def _complete_call(trunk_pair) -> str:
    trunk_pair.as_stack.start_internal_api()
    scenario = CallScenario(
        name="trace-messages",
        calling_number="+86216180001",
        called_number="+8613800138000",
        ring_seconds=0.05,
        talk_seconds=0.05,
    )
    call_id = str(trunk_pair.place_call(scenario))
    finished = trunk_pair.run_until(
        lambda: (outcome := trunk_pair.outcome_for(call_id)) is not None and outcome.released,
        timeout_seconds=15.0,
    )
    assert finished, "call did not complete"
    return call_id


def test_messages_api_returns_invite_for_completed_call(trunk_pair) -> None:
    """Messages API returns trunk + outbound wire capture including INVITE."""
    call_id = _complete_call(trunk_pair)
    api_port = int(trunk_pair.as_stack.settings.internal_api_port)

    payload = _fetch_messages(api_port, call_id)
    messages = payload.get("messages") or []

    assert payload.get("call_id") == call_id
    assert len(messages) >= 2
    texts = [message.get("text", "") for message in messages]
    assert any(text.startswith("INVITE") for text in texts)


def test_messages_include_outbound_call_id_field(trunk_pair) -> None:
    """Response names the outbound B2BUA Call-ID leg."""
    call_id = _complete_call(trunk_pair)
    api_port = int(trunk_pair.as_stack.settings.internal_api_port)

    payload = _fetch_messages(api_port, call_id)
    assert payload.get("outbound_call_id") == outbound_call_id(call_id)
