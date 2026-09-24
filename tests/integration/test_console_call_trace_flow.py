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

"""P15-A integration: Call Trace sequence view markers in CONSOLE_PAGE (REQ-F-056)."""

from __future__ import annotations

import pytest

from console.main import CONSOLE_PAGE

pytestmark = pytest.mark.integration


def test_console_page_has_call_trace_flow_markers() -> None:
    """The Call Trace view exposes SVG ladder + modal shell (ADR-0016 Phase A)."""
    page = CONSOLE_PAGE
    assert 'id="traceFlowSvg"' in page, "sequence SVG missing"
    assert 'id="traceDetailModal"' in page, "detail modal missing"
    assert 'id="traceFlowHeader"' in page, "flow header missing"
    assert "Switch to the Dashboard view for the live trace panel" not in page
    assert "seq-arrow" in page or "seq-step" in page, "sequence render hooks missing"
