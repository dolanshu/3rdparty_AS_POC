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

"""Web console of the AS: FastAPI plus plain HTML/CSS/JS.

The console is a separate process that reaches the AS through its internal API only
(ADR-0002). No third-party front-end libraries, no build step, no Node toolchain
(``AGENT.md`` section 4.4 and 6).
"""
