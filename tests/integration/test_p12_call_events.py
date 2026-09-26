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

"""P12 per-call event integration tests (single call, no load generator).

These tests exercise the AS ``_emit_p12`` path through a real trunk INVITE on the
shared ``trunk_pair`` fixture. They do **not** need the call-load generator or the
4-process Playwright demo stack — that is intentional: the Call-ID alignment bug
(``call_started`` emitted while ``call_id == "-"``) is an AS timing issue visible
on every call once ``start_internal_api()`` wires the fanout.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.integration

_LIFECYCLE_EVENTS = frozenset({"call_started", "call_routed", "call_ended"})


def _wait_for_api_loop(app: Any, *, timeout_seconds: float = 5.0) -> None:
    """Block until the internal API daemon thread captures its event loop."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if getattr(app.state, "_loop", None) is not None:
            return
        time.sleep(0.05)
    pytest.fail("internal API daemon loop not ready on app.state._loop")


def _install_broadcast_capture(app: Any) -> list[dict[str, Any]]:
    """Wrap ``app.state.broadcast`` so every P12 JSON message is retained."""
    captured: list[dict[str, Any]] = []
    lock = threading.Lock()
    real_broadcast = app.state.broadcast

    async def capturing_broadcast(message: str) -> None:
        with lock:
            captured.append(json.loads(message))
        await real_broadcast(message)

    app.state.broadcast = capturing_broadcast
    return captured


def _events_for_call_id(captured: list[dict[str, Any]], call_id: str) -> list[dict[str, Any]]:
    return [event for event in captured if event.get("call_id") == call_id]


def test_single_call_p12_events_share_trunk_call_id(trunk_pair) -> None:
    """One completed call emits started/routed/ended, all keyed by the trunk Call-ID.

    Regression guard for the bug where ``call_started`` was emitted from
    ``CallController.__init__`` while ``call_id`` was still ``"-"``, so filtering
    the Live Trace panel by the real Call-ID showed only ``call_routed`` /
    ``call_ended``.
    """
    trunk_pair.as_stack.start_internal_api()
    app = trunk_pair.as_stack.internal_api.app
    _wait_for_api_loop(app)
    captured = _install_broadcast_capture(app)

    scenario = CallScenario(
        name="p12-lifecycle",
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
    assert finished, "the call did not finish within the timeout"

    # Give the uvicorn loop a moment to drain run_coroutine_threadsafe submissions.
    time.sleep(0.2)

    per_call = _events_for_call_id(captured, call_id)
    events_seen = {event["event"] for event in per_call}
    assert _LIFECYCLE_EVENTS.issubset(events_seen), (
        f"expected full lifecycle on call_id={call_id!r}, "
        f"got events={sorted(events_seen)}, captured={len(captured)} total"
    )
    assert call_id != "-"
    assert not any(event.get("call_id") == "-" for event in per_call)

    dash_started = [event for event in captured if event.get("call_id") == "-"]
    assert not any(event.get("event") == "call_started" for event in dash_started), (
        "call_started must not be emitted under placeholder call_id '-'"
    )
