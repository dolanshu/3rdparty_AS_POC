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

"""Re-export facade for the platform library's sippy adapter (ADR-0009 decision 2).

The implementation moved into the platform library (``as_platform.sip_adapter``); this
module stays so every reference by path — in ``tools/``, ``tests/`` and the frozen ADRs and
LLD — keeps resolving. It adds no behaviour and no state, and it is a permanent part of the
design, not a migration shim.
"""

from __future__ import annotations

from as_platform.sip_adapter import (
    B2BUA_CALL_ID_SUFFIX,
    PASSTHROUGH_HEADERS,
    TRANSACTION_TIMER_NAMES,
    CallLeg,
    build_request_uri,
    cancel_transaction_timers,
    extract_called_number,
    is_allowed_peer,
    outbound_call_id,
)

__all__ = [
    "B2BUA_CALL_ID_SUFFIX",
    "PASSTHROUGH_HEADERS",
    "TRANSACTION_TIMER_NAMES",
    "CallLeg",
    "build_request_uri",
    "cancel_transaction_timers",
    "extract_called_number",
    "is_allowed_peer",
    "outbound_call_id",
]
