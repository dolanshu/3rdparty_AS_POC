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

"""Declarative routing: rule data (``rules``) and decision logic (``engine``).

The split is deliberate. ``rules`` knows about YAML and configuration errors; ``engine``
is a set of pure functions with no sockets, no global state and no clock, so the complete
number translation and routing policy is unit-testable without a network
(``AGENT.md`` section 5 and 12).
"""
