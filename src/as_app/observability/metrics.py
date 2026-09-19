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

"""Re-export facade for :mod:`as_platform.observability.metrics` (ADR-0009 decision 2).

The counters and dispositions live in the platform library; this module only re-exports
their names so ``from as_app.observability.metrics import ...`` keeps resolving for
``tools/``, ``tests/`` and the frozen docs. It adds no behaviour and no state.
"""

from __future__ import annotations

from as_platform.observability.metrics import (
    CallDisposition,
    MetricsRegistry,
    MetricsSnapshot,
    PeerStatus,
    get_metrics_registry,
)

__all__ = [
    "CallDisposition",
    "MetricsRegistry",
    "MetricsSnapshot",
    "PeerStatus",
    "get_metrics_registry",
]
