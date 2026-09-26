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

"""Unit tests for P12 per-call event emission timing on the translation AS controller.

The Call-ID alignment bug is not load-generator-specific: ``call_started`` must not
fire from ``__init__`` (when ``call_id`` is still ``"-"``) and must use the trunk
Call-ID after ``recv_request`` parses the INVITE. These tests catch that contract
without sockets, sippy, or the Playwright demo stack.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from as_platform.call_controller import BaseCallController

from as_app.call_controller import CallController
from as_app.routing.rules import RuleSetStore

pytestmark = pytest.mark.unit


def _app_with_running_loop() -> tuple[Any, asyncio.AbstractEventLoop, list[dict[str, Any]]]:
    """Build a fake FastAPI app whose broadcast runs on a background event loop."""
    app = MagicMock()
    loop = asyncio.new_event_loop()
    captured: list[dict[str, Any]] = []

    async def broadcast(message: str) -> None:
        captured.append(json.loads(message))

    app.state._loop = loop
    app.state.broadcast = broadcast

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, name="p12-unit-loop", daemon=True)
    thread.start()
    return app, loop, captured


def test_call_started_is_not_emitted_during_construction(rules_file: Path) -> None:
    """Constructing a controller must not emit ``call_started`` under call_id '-'."""
    app, loop, captured = _app_with_running_loop()
    try:
        store = RuleSetStore(rules_file)
        controller = CallController(store, app=app)
        assert controller.call_id == "-"
        time.sleep(0.15)
        assert not any(event.get("event") == "call_started" for event in captured)
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_recv_request_emits_call_started_with_trunk_call_id(rules_file: Path) -> None:
    """``recv_request`` must emit ``call_started`` keyed by the INVITE Call-ID header."""
    app, loop, captured = _app_with_running_loop()
    trunk_call_id = "unit-trunk-call-id@127.0.0.1"
    request = MagicMock()
    request.getHFBody.side_effect = lambda header: (
        trunk_call_id if header == "call-id" else ""
    )

    try:
        store = RuleSetStore(rules_file)
        controller = CallController(store, app=app)

        with patch.object(BaseCallController, "recv_request") as mock_super:

            def fake_recv(req: Any, trans: Any) -> None:
                controller.call_id = str(req.getHFBody("call-id"))
                return None

            mock_super.side_effect = fake_recv
            controller.recv_request(request, MagicMock())

        time.sleep(0.25)
        started = [event for event in captured if event.get("event") == "call_started"]
        assert len(started) == 1
        assert started[0]["call_id"] == trunk_call_id
        assert started[0]["call_id"] != "-"
    finally:
        loop.call_soon_threadsafe(loop.stop)
