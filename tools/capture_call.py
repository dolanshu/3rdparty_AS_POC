#!/usr/bin/env python3
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
import shutil
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sippy.Core.EventDispatcher import ED2  # noqa: E402
from sippy.Time.Timeout import Timeout  # noqa: E402

from as_app.bootstrap import AsSettings  # noqa: E402
from as_app.main import AsStack  # noqa: E402
from as_app.observability.tracing import SipMessageRecorder, TraceRecorder  # noqa: E402
from s_sbc_mock.main import MockConfig, SMockApplication  # noqa: E402
from s_sbc_mock.uac import CallOutcome, CallScenario  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "specs" / "message-samples"

#: The scenario every capture uses, so samples stay comparable between runs.
DEFAULT_SCENARIO = CallScenario(
    name="office-to-mobile",
    calling_number="+86216180001",
    called_number="+8613800138000",
)

_METHODS = ("INVITE", "ACK", "BYE", "CANCEL", "PRACK", "UPDATE", "INFO", "OPTIONS")

#: Seconds the loop keeps running after the call was released. The call is over as soon as
#: the trunk leg is released, but the last message of the exchange (the ``200 OK`` that
#: answers the relayed ``BYE``) can still be in flight. Waiting for a short settle window
#: makes the recorded message set deterministic, which the samples and the acceptance
#: report rely on.
SETTLE_SECONDS = 0.3


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


@dataclass(frozen=True)
class CallRun:
    """What one completed call produced, before any sample is written.

    Attributes:
        recorder: Recorder the AS stack wrote every wire message to.
        call_id: SIP Call-ID of the call.
        outcome: What the trunk side of the mock observed.
        trace: Per-Call-ID trace recorder of the AS, routing decisions included.
        trunk_port: UDP port the trunk side of the mock sent from.
        core_port: UDP port of the core side of the mock, the AS next hop.
    """

    recorder: SipMessageRecorder
    call_id: str
    outcome: CallOutcome
    trace: TraceRecorder
    trunk_port: int
    core_port: int


def rewrite_next_hop_ports(rules_file: Path, core_port: int, target_dir: Path) -> Path:
    """Return a copy of the rules file with every next hop port on the core port.

    The shipped rules file pins next hops to demo ports (15061, 15062, ...). The capture
    runs on a dynamically allocated port, so every next hop the rules select must point
    at the mock core side. The rewrite is a capture-only convenience; a real deployment
    keeps the original addresses. The copy is written into ``target_dir`` (a temporary
    directory owned by the caller) so a capture never leaves a file behind in the
    repository.

    Args:
        rules_file: Path of the shipped rules file.
        core_port: UDP port the mock core side listens on.
        target_dir: Directory the rewritten copy is written to.

    Returns:
        Path of the rewritten rules file inside ``target_dir``.
    """
    text = rules_file.read_text(encoding="utf-8")
    rewritten = _NEXT_HOP_PORT_LINE.sub(rf"\g<1>{core_port}\g<2>", text)
    target = target_dir / f"{rules_file.stem}.capture.yaml"
    target.write_text(rewritten, encoding="utf-8")
    return target


def run_call(
    *,
    as_port: int,
    core_port: int,
    trunk_port: int,
    rules_file: Path,
    scenario: CallScenario,
) -> CallRun:
    """Run one call through the real SIP stack and return what happened.

    Args:
        as_port: UDP port the AS receives the trunk on.
        core_port: UDP port of the core side of the mock, the AS next hop.
        trunk_port: UDP port the trunk side of the mock sends from.
        rules_file: Routing rules file the AS loads.
        scenario: The call to place.

    Returns:
        The recorder, Call-ID, trunk-side outcome and trace of the call.

    Raises:
        TimeoutError: When the call did not complete.
    """
    capture_rules_dir = Path(tempfile.mkdtemp(prefix="as-poc-capture-"))
    capture_rules = rewrite_next_hop_ports(rules_file, core_port, capture_rules_dir)
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
        poll = Timeout(_break_after_settle(released, SETTLE_SECONDS), 0.02, -1)
        ED2.loop()
        poll.cancel()
        deadline_timer.cancel()
        if not released():
            raise TimeoutError(f"call {call_id} did not complete within 15 seconds")
        return CallRun(
            recorder=recorder,
            call_id=call_id,
            outcome=mock.uac.outcome_for(call_id) or outcome,
            trace=as_stack.tracer,
            trunk_port=trunk_port,
            core_port=core_port,
        )
    finally:
        as_stack.stop()
        mock.stop()
        shutil.rmtree(capture_rules_dir, ignore_errors=True)


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
    run = run_call(
        as_port=as_port,
        core_port=core_port,
        trunk_port=trunk_port,
        rules_file=rules_file,
        scenario=scenario,
    )
    return write_samples(run.recorder, run.call_id, output_dir, run.trunk_port, run.core_port)


def _break_after_settle(predicate: Any, settle_seconds: float) -> Any:
    """Build a loop callback that stops the loop once a condition has held for a while.

    Args:
        predicate: Condition that marks the end of the call.
        settle_seconds: How long the condition must hold before the loop is stopped.

    Returns:
        A callable suitable for :func:`sippy.Time.Timeout.Timeout`.
    """
    first_hold: list[float] = []

    def poll() -> None:
        """Stop the loop when the end-of-call condition has held long enough."""
        if not predicate():
            first_hold.clear()
            return
        if not first_hold:
            first_hold.append(time.monotonic())
        elif time.monotonic() - first_hold[0] >= settle_seconds:
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

    Every sample left behind by a previous capture is removed first, except the folder's
    ``README.md``, so the directory always holds exactly the messages of the most recent
    call. A capture that produces fewer messages than the previous one can therefore not
    leave orphaned sample files behind.

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
    for stale in list(output_dir.iterdir()):
        if stale.is_file() and stale.name != "README.md":
            stale.unlink()
    written: list[Path] = []
    for index, message in enumerate(recorder.messages_for(call_id), start=1):
        leg = "core" if message.peer.endswith(f":{core_port}") else "trunk"
        name = f"{index:02d}-{message.direction}-{message_token(message.text)}-{leg}.txt"
        path = output_dir / name
        path.write_bytes(message.text.encode("utf-8"))
        written.append(path)
    return written


def display_path(path: Path) -> str:
    """Render a written sample path for the printout.

    ``--output-dir`` may be given as an absolute path or as one relative to the current
    directory (ADR-0007 documents ``--output-dir captures/probe``). ``Path.relative_to``
    raises ``ValueError`` when one side is relative and the other absolute, which is what made
    the relative form crash at the end of an otherwise successful capture, so the path is
    resolved first and falls back to itself when it lies outside the repository.

    Args:
        path: A sample path as returned by :func:`write_samples`.

    Returns:
        The path relative to ``REPO_ROOT`` when it is inside it, the resolved path otherwise.
    """
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


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
        print(f"  {display_path(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
