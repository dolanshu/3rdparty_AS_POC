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

"""Mock of the operator's Service-SBC as seen from the trunk.

The mock stands in for the operator S-SBC boundary: forward side sends INVITE into the AS
trunk (with Route); return side answers the AS outbound INVITE toward IMS. It is built on
the same SIP stack as the AS
(ADR-0001 and ADR-0005) so both sides show identical protocol behaviour.

Nothing in ``src/as_app`` may import from here; the AS has to run against a real S-SBC
without a code change (``AGENT.md`` section 5).
"""
