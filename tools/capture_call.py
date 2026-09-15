#!/usr/bin/env python3
# Copyright 2026 the 3rd-party AS POC authors.
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

"""Capture the SIP messages of a real call into ``docs/specs/message-samples/``.

Message samples are captured, never hand-written (``AGENT.md`` section 7). This tool runs
the AS and the mock S-SBC on loopback UDP, points the AS stack at a
:class:`~as_app.observability.tracing.SipMessageRecorder` and writes every message of the
call to disk, verbatim, using the naming convention of
``docs/specs/message-samples/README.md``::

    <sequence>-<direction>-<method-or-status>[-<qualifier>].txt

``direction`` is relative to the AS — ``in`` is S-SBC to AS, ``out`` is AS to S-SBC — and
the qualifier names the leg: ``trunk`` for the leg towards the emulated S-CSCF, ``core``
for the leg towards the emulated core network.

Ports are allocated dynamically unless they are given on the command line, so the capture
never collides with a running process and never uses 5060 by accident
(``AGENT.md`` section 11).

Usage:
    uv run python tools/capture_call.py
    uv run python tools/capture_call.py --as-port 45060 --core-port 45061
    uv run python tools/capture_call.py --output-dir docs/specs/message-samples
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sippy.Core.EventDispatcher import ED2  # noqa: E402
from sippy.Time.Timeout import Timeout  # noqa: E402

from as_app.bootstrap import AsSettings  # noqa: E402
from as_app.main import AsStack  # noqa: E402
from as_app.observability.tracing import SipMessageRecorder  # noqa: E402
from s_sbc_mock.main import MockConfig, SMockApplication  # noqa: E402
from s_sbc_mock.uac import CallScenario  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "specs" / "message-samples"

#: The scenario every capture uses, so samples stay comparable between runs.
DEFAULT_SCENARIO = CallScenario(
    name="office-to-mobile",
    calling_number="+86216180001",
    called_number="+8613800138000",
)

_METHODS = ("INVITE", "ACK", "BYE", "CANCEL", "PRACK", "UPDATE", "INFO", "OPTIONS")


def free_udp_port() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def message_token(text: str) -> str:
    """Return the method or status code of a raw SIP message.

    Args:
        text: A complete SIP message.

    Returns:
        The lower case method name, the status code, or ``message``.
    """
    start_line = text.split("\r\n", 1)[0]
    fields = start_line.split(" ")
    if start_line.startswith("SIP/2.0"):
        return fields[1] if len(fields) > 1 else "message"
    for candidate in _METHODS:
        if start_line.startswith(candidate + " "):
            return candidate.lower()
    return "message"


def call_id_of(text: str) -> str:
    """Return the Call-ID of a raw SIP message.

    Args:
        text: A complete SIP message.

    Returns:
        The Call-ID value, or ``"-"`` when the message carries none.
    """
    match = re.search(r"^Call-ID:[ \t]*(\S+)[ \t\r]*$", text, re.IGNORECASE | re.MULTILINE)
    return match.group(1) if match is not None else "-"


_NEXT_HOP_PORT_LINE = re.compile(r"^(\s+port:\s+)\d+(\s.*)?$", re.MULTILINE)


def _rewrite_next_hop_ports(rules_file: Path, core_port: int) -> Path:
    """Return a copy of the rules file with every next hop port on the core port.

    The shipped rules file pins next hops to demo ports (15061, 15062, ...). The capture
    runs on a dynamically allocated port, so every next hop the rules select must point
    at the mock core side. The rewrite is a capture-only convenience; a real deployment
    keeps the original addresses.

    Args:
        rules_file: Path of the shipped rules file.
        core_port: UDP port the mock core side listens on.

    Returns:
        Path of the rewritten rules file written next to the original.
    """
    text = rules_file.read_text(encoding="utf-8")
    rewritten = _NEXT_HOP_PORT_LINE.sub(rf"\g<1>{core_port}\g<2>", text)
    target = rules_file.with_suffix(".capture.yaml")
    target.write_text(rewritten, encoding="utf-8")
    return target


def run_capture(
    *,
    as_port: int,
    core_port: int,
    trunk_port: int,
    rules_file: Path,
    scenario: CallScenario,
    output_dir: Path,
) -> list[Path]:
    """Run one call and write its messages to the sample directory.

    Args:
        as_port: UDP port the AS receives the trunk on.
        core_port: UDP port of the core side of the mock, the AS next hop.
        trunk_port: UDP port the trunk side of the mock sends from.
        rules_file: Routing rules file the AS loads.
        scenario: The call to place.
        output_dir: Directory the samples are written to.

    Returns:
        The paths that were written.

    Raises:
        TimeoutError: When the call did not complete.
    """
    capture_rules = _rewrite_next_hop_ports(rules_file, core_port)
    settings = AsSettings(
        _env_file=None,
        sip_listen_address="127.0.0.1",
        sip_listen_port=as_port,
        sbc_peer_address="127.0.0.1",
        sbc_peer_port=core_port,
        allowed_peers=["127.0.0.1"],
        rules_file=capture_rules,
        log_payloads=True,
    )
    recorder = SipMessageRecorder()
    as_stack = AsStack(settings, sip_logger=recorder)
    as_stack.start()
    mock = SMockApplication(
        MockConfig(
            listen_address="127.0.0.1",
            listen_port=core_port,
            as_address="127.0.0.1",
            as_port=as_port,
            scenarios=[scenario],
        ),
        sip_logger=SipMessageRecorder(),
        uac_local_port=trunk_port,
    )
    mock.start()
    try:
        call_id = mock.uac.place_call(scenario)
        outcome = mock.uac.outcome_for(call_id)
        assert outcome is not None

        def released() -> bool:
            current = mock.uac.outcome_for(call_id) or outcome
            return bool(current.released)

        deadline_timer = Timeout(ED2.breakLoop, 15.0, 1)
        poll = Timeout(_break_when(released), 0.02, -1)
        ED2.loop()
        poll.cancel()
        deadline_timer.cancel()
        if not released():
            raise TimeoutError(f"call {call_id} did not complete within 15 seconds")
        return write_samples(recorder, call_id, output_dir, trunk_port, core_port)
    finally:
        as_stack.stop()
        mock.stop()


def _break_when(predicate: Any) -> Any:
    """Build a loop callback that stops the loop when a condition holds.

    Args:
        predicate: Condition to wait for.

    Returns:
        A callable suitable for :func:`sippy.Time.Timeout.Timeout`.
    """

    def poll() -> None:
        if predicate():
            ED2.breakLoop()

    return poll


def write_samples(
    recorder: SipMessageRecorder,
    call_id: str,
    output_dir: Path,
    trunk_port: int,
    core_port: int,
) -> list[Path]:
    """Write the captured messages of one call to disk.

    Args:
        recorder: The recorder the AS stack was writing to.
        call_id: SIP Call-ID of the call to write.
        output_dir: Directory the samples are written to.
        trunk_port: UDP port of the trunk side of the mock.
        core_port: UDP port of the core side of the mock.

    Returns:
        The paths that were written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("[0-9][0-9]-*.txt"):
        stale.unlink()
    written: list[Path] = []
    for index, message in enumerate(recorder.messages_for(call_id), start=1):
        leg = "core" if message.peer.endswith(f":{core_port}") else "trunk"
        name = f"{index:02d}-{message.direction}-{message_token(message.text)}-{leg}.txt"
        path = output_dir / name
        path.write_bytes(message.text.encode("utf-8"))
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    """Run the capture.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Capture the SIP messages of a real call")
    parser.add_argument("--as-port", type=int, default=None, help="UDP port of the AS")
    parser.add_argument(
        "--core-port", type=int, default=None, help="UDP port of the mock core side"
    )
    parser.add_argument(
        "--trunk-port", type=int, default=None, help="UDP port of the mock trunk side"
    )
    parser.add_argument(
        "--rules-file", type=Path, default=REPO_ROOT / "config" / "routing_rules.yaml"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--caller", default=DEFAULT_SCENARIO.calling_number)
    parser.add_argument("--called", default=DEFAULT_SCENARIO.called_number)
    args = parser.parse_args(argv)

    as_port = args.as_port or free_udp_port()
    core_port = args.core_port or free_udp_port()
    trunk_port = args.trunk_port or free_udp_port()
    scenario = CallScenario(
        name=DEFAULT_SCENARIO.name, calling_number=args.caller, called_number=args.called
    )
    print(f"as port    : 127.0.0.1:{as_port}")
    print(f"core port  : 127.0.0.1:{core_port}  (AS next hop)")
    print(f"trunk port : 127.0.0.1:{trunk_port}  (emulated S-CSCF)")
    written = run_capture(
        as_port=as_port,
        core_port=core_port,
        trunk_port=trunk_port,
        rules_file=args.rules_file,
        scenario=scenario,
        output_dir=args.output_dir,
    )
    print(f"captured   : {len(written)} messages")
    for path in written:
        print(f"  {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
