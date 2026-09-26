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

"""Parse the top SIP ``Route`` header entry.

A request travelling through a loose-routing chain carries its ``Route``
set leftmost-route-first (RFC 3261 §12.2).  The AS reads the top entry to
decide where to send the outbound leg — that is the operator's S-SBC
hop the trunk inserted before us.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["parse_top_route_target"]


# ``<sip:host[:port];lr>`` — the form sippy produces for Route entries.
_ROUTE_URI_RE = re.compile(r"<sip:([^:>;\s]+)(?::(\d+))?[^>]*>")


def parse_top_route_target(
    request: Any, *, default_port: int = 5060
) -> tuple[str, int] | None:
    """Return the ``(host, port)`` of the top Route URI, or ``None``.

    Args:
        request: A sippy request object with ``getHFBodys("route")``,
            or ``None``.
        default_port: Used when the Route URI omits a port.
    """
    if request is None:
        return None
    try:
        bodies = request.getHFBodys("route")
    except (AttributeError, TypeError):
        return None
    if not bodies:
        return None
    try:
        raw = bodies[0].getCopy() if hasattr(bodies[0], "getCopy") else bodies[0]
        top = str(raw)
    except (AttributeError, TypeError, IndexError):
        return None
    m = _ROUTE_URI_RE.search(top)
    if not m:
        return None
    host = m.group(1)
    port = int(m.group(2)) if m.group(2) else default_port
    return (host, port)
