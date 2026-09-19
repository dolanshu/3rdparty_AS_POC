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

"""Discover where the capacity boundary of the chained AS topology is (P9.5).

P9.5 is a **read-only** item (``docs/phase2-plan.md`` section 3): the skeleton is not
changed, and what is added here is a **load generator plus observation**. Its deliverable is
**constraints, never a headline number** — the approved ``AGENT.md`` section 2 relaxation
(2026-09-19, plan section 8 item 1, D10) permits a capacity harness but **forbids a published
calls-per-second or latency figure**. Nothing this tool prints may be read as a benchmark;
each measurement is written below as a boundary statement.

**Load shaping.** The probe runs the real stacks in one interpreter — ``S-CSCF -> AS-1
(anti-fraud) -> AS-2 (number translation) -> core``, wired by configuration only, exactly as
``tools/chained_as_probe.py`` does — and places calls at an **escalating offered concurrency**.
A *level* is ``N`` calls placed back to back before the event loop is driven, so ``N`` is the
offered concurrency of that level (the calls are in flight together, not one after another).
The levels default to ``1, 2, 4, 8, 16, 32, 64`` and the run stops escalating at the first
level whose completion drops below its offer — that is the boundary being looked for. Every
caller is taken from the screening data's **allow-listed fleet prefix** and given a distinct
number, so AS-1's call-rate window and reputation never confound the measurement: the load
measures the topology, not the screening policy.

**What is measured, and why each is a constraint rather than a benchmark.**

1. **Call completion under load** — how many of the ``N`` offered calls reach ``200 OK`` and
   release, how many end non-``200``, how many are still pending when the level's cap
   expires, and how many reached the core. The constraint is *where completion first drops*:
   the offered concurrency at which the chain stops completing every call. It is reported as
   an offered level, not as a rate.
2. **Loop responsiveness** — a poll timer measures the largest gap between two of its own
   runs while the level is in flight. ``ED2.loop()`` is a single process-wide, blocking,
   single-threaded event dispatcher (``AGENT.md`` section 6, plan section 6): every AS
   instance and the mock share one loop in this tool, so this gap shows the loop itself as
   the serialisation point. It is a constraint on loop responsiveness, **not** a latency
   measurement of a call.
3. **The no-answer timer becomes the ceiling** — each controller tears a relayed leg down
   after a fixed 3-second no-answer timeout (``_DEFAULT_NEXT_HOP_EXPIRE`` in both
   controllers). Under load that fixed wall-clock timeout, not any resource limit, is what
   turns a slow call into a failed one. Observed as the non-``200``/pending counts, never as
   a latency figure.
4. **The unreachable-hop timer population (the P8a lesson)** — a second, separate chain
   points AS-2's next hop at a port nothing listens on. Each relayed leg is given 3 seconds
   to answer, but sippy's client transaction towards the unreachable hop stays armed for
   ``timerB`` = 32 seconds and is reaped later still by ``timerC`` (plan section 3, P8a
   *What was learned*, point 3; section 6). The probe counts how many transactions remain
   armed while the calls are still unresolved, so the constraint is the *size and lifetime
   of that population under a burst* — a memory and timer-heap cost, not a throughput
   figure. The shipped mobile rule lists a primary and a failover hop, so each call leaves
   one armed transaction **per hop tried**: the observed population is the burst multiplied
   by the number of hops in the rule set. What the probe found is stronger than the P8a
   lesson: the failover hop's own no-answer timer does not fire, so the application never
   releases the call, and it is ``timerB`` — not the application — that ends it.
5. **Retransmission towards a silent hop** — the same chain counts the INVITE transmissions
   AS-2 makes towards the unreachable hop, so the retransmission population is observed
   rather than assumed (``timerA`` doubles its interval and only ``timerB`` stops it).

**What this tool is not.** It publishes no calls-per-second and no latency figure, and it
asserts no target throughput. It is a **guard on the probe's own integrity**, not on
performance: it exits non-zero when the positive control (one call through the chain at
offered level 1) fails, or when the unreachable-hop observation does not actually see an
armed transaction after the application gave up — because then the constraint it claims to
have measured was not measured at all. A degradation finding is a **result**, not a failure,
and never changes the exit code.

The run is time-boxed and terminating: each level has its own cap (``--level-timeout``), the
escalation stops at the first degradation, and the unreachable-hop window is short because it
observes the 3-second application timeout, not the 32-second timer. It is a design
instrument, not a test: pytest does not collect it, it is not in ``make test``, and it is not
wired into CI. Ports are allocated dynamically, so it never collides with a running process.

Usage:
    uv run python tools/capacity_probe.py
    uv run python tools/capacity_probe.py --levels 1,2,4,8,16
    uv run python tools/capacity_probe.py --level-timeout 8 --skip-unreachable
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
for path in (str(REPO_ROOT / "src"), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from capture_call import free_udp_port, rewrite_next_hop_ports  # noqa: E402
from sippy.Core.EventDispatcher import ED2  # noqa: E402
from sippy.Time.Timeout import Timeout  # noqa: E402

from anti_fraud_as.bootstrap import FraudAsSettings  # noqa: E402
from anti_fraud_as.main import FraudAsStack  # noqa: E402
from as_app.bootstrap import AsSettings  # noqa: E402
from as_app.main import AsStack  # noqa: E402
from as_app.observability.logging import configure_logging  # noqa: E402
from as_app.observability.metrics import MetricsRegistry  # noqa: E402
from as_app.observability.tracing import SipMessageRecorder, TraceRecorder  # noqa: E402
from s_sbc_mock.main import MockConfig, SMockApplication  # noqa: E402
from s_sbc_mock.uac import CallOutcome, CallScenario  # noqa: E402

#: Width of the left column of the transcript, so every value lines up.
_LABEL_WIDTH = 18

#: Offered concurrency of each level, in calls placed back to back before the loop is driven.
DEFAULT_CONCURRENCY_LEVELS: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64)

#: How long one level is given to complete before it is counted as pending.
DEFAULT_LEVEL_TIMEOUT_SECONDS = 12.0

#: How long the unreachable-hop chain is driven. It observes the application's 3-second
#: no-answer timeout, not the 32-second ``timerB``, but a call is only released after the
#: rule set's primary **and** failover hop have each timed out, so the window has to cover
#: two of them plus the relay. It must stay **below** ``timerB``: this probe measures the
#: **armed** population, and once ``timerB`` fires the arm is gone — the entries themselves
#: linger in ``tclient`` (the table is not reaped).
DEFAULT_UNREACHABLE_WINDOW_SECONDS = 9.0

#: How many calls the unreachable-hop observation places in one burst.
DEFAULT_UNREACHABLE_CALLS = 4

#: Poll interval of the loop driver, in seconds. It is also the resolution of the loop-gap
#: measurement: a gap larger than this means the loop was busy for that long.
POLL_SECONDS = 0.02

#: The screening data allow-lists this fleet prefix, so a burst from it is delivered however
#: many calls arrive inside the call-rate window (``config/caller_screening.yaml``). Every
#: caller is drawn from it so the load measures the topology, not the screening policy.
ALLOWED_CALLER_PREFIX = "+86138001380"

#: Called number of every load call; AS-1 never rewrites it, AS-2 translates it.
CALLED_NUMBER = "+8613800138000"


@dataclass
class LoopGap:
    """Largest gap between two runs of the loop driver, in seconds.

    The driver's poll timer runs inside the sippy event loop, so a gap larger than the poll
    interval means the loop was busy for that long — the observable form of "the loop is the
    serialisation point" (``AGENT.md`` section 6).

    Attributes:
        max_gap: Largest observed gap between two consecutive polls.
        last: Monotonic instant of the previous poll.
    """

    max_gap: float = 0.0
    last: float | None = None

    def beat(self) -> None:
        """Record one poll of the loop driver."""
        now = time.monotonic()
        if self.last is not None:
            self.max_gap = max(self.max_gap, now - self.last)
        self.last = now


@dataclass
class LevelObservation:
    """What one offered-concurrency level produced.

    Attributes:
        offered: Calls placed back to back for this level (the offered concurrency).
        completed: Calls that reached ``200 OK`` and released.
        non_200: Calls that released with a final status other than ``200``.
        pending: Calls still in flight when the level cap expired.
        reached_core: Calls whose INVITE reached the emulated core.
        loop_gap_seconds: Largest loop-driver gap observed while the level was in flight.
        finished_within_cap: Whether every offered call released inside the level cap.
    """

    offered: int
    completed: int
    non_200: int
    pending: int
    reached_core: int
    loop_gap_seconds: float
    finished_within_cap: bool


@dataclass
class UnreachableObservation:
    """What the unreachable-hop chain produced after the application gave up.

    Attributes:
        placed: Calls placed in the burst.
        released: Calls the application gave up on (the trunk leg was released).
        gave_up: Whether every call was released inside the window, so the population
            counted below is genuinely post-give-up.
        armed_transactions: Client transactions still in sippy's table after give-up.
        armed_timerb: How many of those still have ``timerB`` armed.
        timerb_seconds: The ``timerB`` interval the surviving timers carry.
        invite_transmissions: INVITEs AS-2 sent towards the silent hop, retransmits included.
    """

    placed: int
    released: int
    gave_up: bool
    armed_transactions: int
    armed_timerb: int
    timerb_seconds: float | None
    invite_transmissions: int


@dataclass
class _Chain:
    """One running chain of two B2BUAs plus the mock, and its temporary rule file.

    Attributes:
        as1: The anti-fraud instance (AS-1).
        as2: The number-translation instance (AS-2).
        mock: The mock S-SBC (trunk UAC and core UAS).
        as1_recorder: SIP message recorder of AS-1.
        as2_recorder: SIP message recorder of AS-2.
        rules_dir: Temporary directory holding the rewritten rule file.
        ports: Named ports of the chain, for the transcript.
    """

    as1: FraudAsStack
    as2: AsStack
    mock: SMockApplication
    as1_recorder: SipMessageRecorder
    as2_recorder: SipMessageRecorder
    rules_dir: Path
    ports: dict[str, int] = field(default_factory=dict)

    def stop(self) -> None:
        """Stop every stack and remove the temporary rule file."""
        self.as1.stop()
        self.as2.stop()
        self.mock.stop()
        shutil.rmtree(self.rules_dir, ignore_errors=True)


def draw_loop_until(predicate: Any, timeout_seconds: float, heartbeat: Any = None) -> bool:
    """Drive the sippy event loop until a condition holds or the timeout expires.

    Args:
        predicate: Condition that marks the end of the wait.
        timeout_seconds: How long to keep driving the loop.
        heartbeat: Optional callable invoked on every poll, used to measure loop gaps.

    Returns:
        ``True`` when the condition became true, ``False`` on timeout.
    """
    state = {"done": False}

    def poll() -> None:
        if heartbeat is not None:
            heartbeat()
        if predicate():
            state["done"] = True
            ED2.breakLoop()

    timer = Timeout(poll, POLL_SECONDS, -1)
    deadline = Timeout(ED2.breakLoop, timeout_seconds, 1)
    try:
        ED2.loop(timeout=timeout_seconds)
    finally:
        timer.cancel()
        deadline.cancel()
    return bool(state["done"] or predicate())


def build_chain(
    *,
    rules_file: Path,
    screening_file: Path,
    as2_next_hop_port: int,
    mock_listen_port: int,
) -> _Chain:
    """Run one chained topology wired by configuration only.

    AS-1's allowed-relay next hop is AS-2's listen address, and AS-2 selects its next hop
    from the rule set (ADR-0008 decision 1). Each stack gets its own trace recorder, metrics
    registry and SIP message recorder, because they default to process-wide singletons and a
    shared one would mix the two instances.

    Args:
        rules_file: The shipped rules file AS-2 loads.
        screening_file: The shipped screening data file AS-1 loads.
        as2_next_hop_port: Port AS-2's rule-selected next hop is rewritten to.
        mock_listen_port: Port the mock's core (UAS) side binds.

    Returns:
        The running chain.
    """
    as1_port = free_udp_port()  # AS-1: the anti-fraud instance
    as2_port = free_udp_port()  # AS-2: the number-translation instance
    trunk_port = free_udp_port()  # the emulated S-CSCF trigger, AS-1's trunk peer

    rules_dir = Path(tempfile.mkdtemp(prefix="as-poc-capacity-"))
    chained_rules = rewrite_next_hop_ports(rules_file, as2_next_hop_port, rules_dir)

    as1_recorder = SipMessageRecorder()
    as2_recorder = SipMessageRecorder()
    as1 = FraudAsStack(
        FraudAsSettings(
            _env_file=None,
            fraud_sip_listen_address="127.0.0.1",
            fraud_sip_listen_port=as1_port,
            fraud_sbc_peer_address="127.0.0.1",
            fraud_sbc_peer_port=as2_port,
            fraud_allowed_peers=["127.0.0.1"],
            fraud_screening_file=screening_file,
            log_payloads=False,
        ),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
        sip_logger=as1_recorder,
    )
    as2 = AsStack(
        AsSettings(
            _env_file=None,
            sip_listen_address="127.0.0.1",
            sip_listen_port=as2_port,
            sbc_peer_address="127.0.0.1",
            sbc_peer_port=as2_next_hop_port,
            allowed_peers=["127.0.0.1"],
            rules_file=chained_rules,
            log_payloads=False,
        ),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
        sip_logger=as2_recorder,
    )
    mock = SMockApplication(
        MockConfig(
            listen_address="127.0.0.1",
            listen_port=mock_listen_port,
            as_address="127.0.0.1",
            as_port=as1_port,
        ),
        sip_logger=SipMessageRecorder(),
        uac_local_port=trunk_port,
    )
    as1.start()
    as2.start()
    mock.start()
    return _Chain(
        as1=as1,
        as2=as2,
        mock=mock,
        as1_recorder=as1_recorder,
        as2_recorder=as2_recorder,
        rules_dir=rules_dir,
        ports={
            "as1": as1_port,
            "as2": as2_port,
            "trunk": trunk_port,
            "core": mock_listen_port,
        },
    )


def load_scenario(index: int) -> CallScenario:
    """Build the scenario of one load call.

    The caller is drawn from the allow-listed fleet prefix with a distinct number, so AS-1's
    call-rate window and reputation never reject a load call and the measurement stays about
    the topology.

    Args:
        index: Position of the call inside the whole run, kept unique per call.

    Returns:
        The scenario to place.
    """
    return CallScenario(
        name=f"capacity-{index:04d}",
        calling_number=f"{ALLOWED_CALLER_PREFIX}{index:03d}",
        called_number=CALLED_NUMBER,
    )


def place_burst(mock: SMockApplication, offered: int, *, first_index: int) -> list[str]:
    """Place ``offered`` calls back to back and return their Call-IDs.

    Placing them without driving the loop is what makes them concurrent: they are all in
    flight together, which is the offered concurrency of the level.

    Args:
        mock: The running mock S-SBC.
        offered: How many calls to place.
        first_index: Index of the first call, so caller numbers stay unique per run.

    Returns:
        The Call-IDs, in placement order.
    """
    return [mock.uac.place_call(load_scenario(first_index + offset)) for offset in range(offered)]


def observe_level(
    mock: SMockApplication, offered: int, *, first_index: int, cap: float
) -> LevelObservation:
    """Place one offered-concurrency level and observe what completes.

    Args:
        mock: The running mock S-SBC.
        offered: Calls placed back to back for this level.
        first_index: Index of the first call, so caller numbers stay unique per run.
        cap: How long the level is given to complete.

    Returns:
        What the level produced.
    """
    gap = LoopGap()
    core_before = len(mock.uas.received_invites)
    call_ids = place_burst(mock, offered, first_index=first_index)

    def all_released() -> bool:
        return all(
            bool((mock.uac.outcome_for(call_id) or CallOutcome("", "")).released)
            for call_id in call_ids
        )

    finished = draw_loop_until(all_released, cap, heartbeat=gap.beat)

    outcomes = [mock.uac.outcome_for(call_id) for call_id in call_ids]
    completed = sum(1 for outcome in outcomes if outcome is not None and outcome.status == 200)
    non_200 = sum(
        1
        for outcome in outcomes
        if outcome is not None and outcome.released and outcome.status != 200
    )
    pending = sum(1 for outcome in outcomes if outcome is None or not outcome.released)
    return LevelObservation(
        offered=offered,
        completed=completed,
        non_200=non_200,
        pending=pending,
        reached_core=len(mock.uas.received_invites) - core_before,
        loop_gap_seconds=gap.max_gap,
        finished_within_cap=finished,
    )


def _armed_client_transactions(manager: Any) -> list[Any]:
    """Return the client transactions a sippy manager still holds.

    Args:
        manager: A sippy ``SipTransactionManager``.

    Returns:
        The transactions in its ``tclient`` table, or an empty list when it is stopped.
    """
    table = getattr(manager, "tclient", None)
    if not table:
        return []
    return list(table.values())


def _timerb_interval(transaction: Any) -> float | None:
    """Return the interval of a transaction's armed ``timerB``, when it has one.

    Args:
        transaction: A sippy ``SipTransaction``.

    Returns:
        The interval in seconds, or ``None`` when ``timerB`` is not armed.
    """
    timer = getattr(transaction, "teB", None)
    if timer is None or getattr(timer, "cb_func", None) is None:
        return None
    return float(getattr(timer, "ival", 0.0))


def count_invite_transmissions(recorder: SipMessageRecorder) -> int:
    """Count the INVITEs a stack sent, retransmissions included.

    Args:
        recorder: SIP message recorder of that stack.

    Returns:
        How many outbound INVITEs the stack wrote.
    """
    return sum(
        1
        for message in recorder.messages
        if message.direction == "out" and message.text.upper().startswith("INVITE")
    )


def observe_unreachable_hop(
    chain: _Chain, *, calls: int, window_seconds: float, first_index: int
) -> UnreachableObservation:
    """Observe the timer population a burst leaves behind when a hop never answers.

    The application gives the relayed leg up after its fixed no-answer timeout, but sippy's
    client transaction towards the unreachable hop stays armed for ``timerB`` and is reaped
    later still by ``timerC`` (P8a lesson). This places one burst, waits for the application
    to give up, and then counts what is still armed.

    The window has to cover **every** hop the rule set tries: the shipped mobile rule lists
    a primary and a failover hop, and :func:`capture_call.rewrite_next_hop_ports` points both
    at the silent port, so a call is only released after two no-answer timeouts. That is why
    the default window is a multiple of the 3-second timeout, not one timeout plus margin.

    Args:
        chain: The chain whose AS-2 next hop points at a silent port.
        calls: How many calls to place in the burst.
        window_seconds: How long to drive the loop; must exceed one timeout per hop.
        first_index: Index of the first call, so caller numbers stay unique per run.

    Returns:
        What survived the application's give-up.
    """
    call_ids = place_burst(chain.mock, calls, first_index=first_index)

    def all_released() -> bool:
        return all(
            bool((chain.mock.uac.outcome_for(call_id) or CallOutcome("", "")).released)
            for call_id in call_ids
        )

    gave_up = draw_loop_until(all_released, window_seconds)
    transactions = _armed_client_transactions(chain.as2.transaction_manager)
    intervals = [
        interval for interval in map(_timerb_interval, transactions) if interval is not None
    ]
    released = sum(
        1
        for call_id in call_ids
        if bool((chain.mock.uac.outcome_for(call_id) or CallOutcome("", "")).released)
    )
    return UnreachableObservation(
        placed=calls,
        released=released,
        gave_up=gave_up,
        armed_transactions=len(transactions),
        armed_timerb=len(intervals),
        timerb_seconds=intervals[0] if intervals else None,
        invite_transmissions=count_invite_transmissions(chain.as2_recorder),
    )


def parse_levels(value: str) -> tuple[int, ...]:
    """Parse the ``--levels`` option.

    Args:
        value: Comma separated offered concurrency levels, for example ``1,2,4``.

    Returns:
        The levels, in the order given.

    Raises:
        argparse.ArgumentTypeError: When a level is not a positive integer.
    """
    levels: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            level = int(part)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"not an integer: {part!r}") from error
        if level <= 0:
            raise argparse.ArgumentTypeError(f"level must be positive: {level}")
        levels.append(level)
    if not levels:
        raise argparse.ArgumentTypeError("at least one level is required")
    return tuple(levels)


def main(argv: list[str] | None = None) -> int:
    """Run the capacity probe and print the constraints it observed.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` when the probe's positive control held and its
        unreachable-hop measurement was real, ``1`` otherwise. A degradation finding never
        changes the exit code — it is the result the probe is looking for.
    """
    parser = argparse.ArgumentParser(
        description="Probe the capacity boundary of the chained AS topology"
    )
    parser.add_argument(
        "--levels",
        type=parse_levels,
        default=DEFAULT_CONCURRENCY_LEVELS,
        help="comma separated offered concurrency levels, escalating",
    )
    parser.add_argument(
        "--level-timeout",
        type=float,
        default=DEFAULT_LEVEL_TIMEOUT_SECONDS,
        help="seconds one offered level is given to complete",
    )
    parser.add_argument(
        "--unreachable-window",
        type=float,
        default=DEFAULT_UNREACHABLE_WINDOW_SECONDS,
        help="seconds the unreachable-hop chain is driven",
    )
    parser.add_argument(
        "--unreachable-calls",
        type=int,
        default=DEFAULT_UNREACHABLE_CALLS,
        help="calls placed in the unreachable-hop burst",
    )
    parser.add_argument(
        "--skip-unreachable",
        action="store_true",
        help="run only the escalating-load section",
    )
    parser.add_argument(
        "--log-level",
        default="ERROR",
        help="log level of the application log; raise it to see the controllers' warnings",
    )
    parser.add_argument(
        "--rules-file", type=Path, default=REPO_ROOT / "config" / "routing_rules.yaml"
    )
    parser.add_argument(
        "--screening-file",
        type=Path,
        default=REPO_ROOT / "config" / "caller_screening.yaml",
    )
    args = parser.parse_args(argv)

    configure_logging(args.log_level, structured=False)

    print("chained AS POC - capacity boundary probe (read-only, observation only)")
    print(
        "topology   : emulated S-CSCF --UDP--> AS-1 anti-fraud --UDP--> AS-2 number "
        "translation --UDP--> emulated core"
    )
    print(
        "note       : all three stacks share one process-wide ED2 loop in this tool; in "
        "production each instance is its own process"
    )
    print(
        "note       : this probe publishes no calls-per-second and no latency figure "
        "(plan section 8 item 1, D10); every value below is a constraint"
    )
    print()

    control_ok = False
    degradation_level: int | None = None
    unreachable_ok = False
    results: list[bool] = []

    # ---- 1. escalating offered load towards the healthy chain ----------------------------
    core_port = free_udp_port()
    chain = build_chain(
        rules_file=args.rules_file,
        screening_file=args.screening_file,
        as2_next_hop_port=core_port,
        mock_listen_port=core_port,
    )
    print(
        f"ports      : AS-1 127.0.0.1:{chain.ports['as1']}, AS-2 127.0.0.1:{chain.ports['as2']}, "
        f"trunk {chain.ports['trunk']}, core {chain.ports['core']}"
    )
    print("wiring     : AS-1 next hop = AS-2 listen address; AS-2 next hop = the rule set")
    print()
    try:
        # Positive control: one call through the whole chain must complete, or nothing else
        # the probe reports means anything.
        control = observe_level(chain.mock, 1, first_index=0, cap=args.level_timeout)
        control_ok = control.completed == 1 and control.reached_core == 1
        print("[control] one call through the chain at offered level 1")
        print(f"{'completed':<{_LABEL_WIDTH}}: {control.completed} of 1")
        print(f"{'reached core':<{_LABEL_WIDTH}}: {control.reached_core} of 1")
        print()

        print("[1/2] escalating offered concurrency towards the chained topology")
        header = (
            f"{'level':>6}  {'offered':>7}  {'completed':>9}  {'non-200':>7}  "
            f"{'pending':>7}  {'at core':>7}  {'loop gap':>9}  {'in cap':>6}"
        )
        print(header)
        first_index = 100
        observations: list[LevelObservation] = []
        for offered in args.levels:
            observation = observe_level(
                chain.mock, offered, first_index=first_index, cap=args.level_timeout
            )
            observations.append(observation)
            first_index += offered
            print(
                f"{offered:>6}  {observation.offered:>7}  {observation.completed:>9}  "
                f"{observation.non_200:>7}  {observation.pending:>7}  "
                f"{observation.reached_core:>7}  {observation.loop_gap_seconds:>8.2f}s  "
                f"{'yes' if observation.finished_within_cap else 'no':>6}"
            )
            if observation.completed < observation.offered and degradation_level is None:
                degradation_level = offered
                break
        print()

        print("  constraint: call completion under load")
        if degradation_level is None:
            highest = observations[-1].offered
            print(
                f"    no degradation within the configured levels: every call completed up to "
                f"offered level {highest}"
            )
            print(
                "    the boundary is above the configured range; escalate with --levels to reach it"
            )
        else:
            boundary = next(o for o in observations if o.offered == degradation_level)
            print(
                f"    first degradation at offered level {degradation_level}: "
                f"{boundary.completed} of {boundary.offered} completed, "
                f"{boundary.non_200} non-200, {boundary.pending} pending, "
                f"{boundary.reached_core} reached the core"
            )
            print(
                "    the chain accepts the whole burst and degrades per call: it does not "
                "refuse load or answer 503/overload (no admission control)"
            )
        worst_gap = max((o.loop_gap_seconds for o in observations), default=0.0)
        print(
            f"    loop gap: largest gap between two polls of the single process-wide ED2 loop "
            f"was {worst_gap:.2f}s while load was in flight"
        )
        print(
            "    constraint: the event loop is the serialisation point — one blocking, "
            "single-threaded ED2 dispatches every message of both instances and the mock, so "
            "a busy loop delays every call's timers and responses alike"
        )
        print(
            "    constraint: the fixed 3-second no-answer timeout of each controller is what "
            "turns a slow call into a failed one under load; the boundary is a wall-clock "
            "timeout, not a resource limit"
        )
        print(
            "    caveat: this ceiling is the harness's — one interpreter runs all three "
            "stacks; production gives each AS instance its own process and its own loop, so "
            "the number of instances is not the constraint this measures"
        )
        print()
        results.append(control_ok)
    finally:
        chain.stop()

    # ---- 2. the timer population a silent hop leaves behind ------------------------------
    if args.skip_unreachable:
        print("[2/2] unreachable-hop observation skipped (--skip-unreachable)")
    else:
        unreachable_port = free_udp_port()  # nothing binds this: the hop never answers
        silent_core_port = free_udp_port()  # the mock's core side, never reached
        silent_chain = build_chain(
            rules_file=args.rules_file,
            screening_file=args.screening_file,
            as2_next_hop_port=unreachable_port,
            mock_listen_port=silent_core_port,
        )
        try:
            print(
                f"[2/2] burst towards an unreachable hop (AS-2 next hop = silent port "
                f"{unreachable_port})"
            )
            unreachable = observe_unreachable_hop(
                silent_chain,
                calls=args.unreachable_calls,
                window_seconds=args.unreachable_window,
                first_index=5000,
            )
            unreachable_ok = unreachable.armed_timerb > 0 and unreachable.timerb_seconds is not None
            print(f"{'calls placed':<{_LABEL_WIDTH}}: {unreachable.placed}")
            print(
                f"{'trunk released':<{_LABEL_WIDTH}}: {unreachable.released} of "
                f"{unreachable.placed} (0 when the failover hop's timer never fires)"
            )
            print(
                f"{'still in tclient':<{_LABEL_WIDTH}}: {unreachable.armed_transactions} "
                "client transactions"
            )
            print(
                f"{'timerB armed':<{_LABEL_WIDTH}}: {unreachable.armed_timerb} of "
                f"{unreachable.armed_transactions}"
            )
            print(
                f"{'timerB interval':<{_LABEL_WIDTH}}: "
                f"{unreachable.timerb_seconds if unreachable.timerb_seconds is not None else '-'}s"
            )
            print(
                f"{'INVITE transmits':<{_LABEL_WIDTH}}: {unreachable.invite_transmissions} "
                "towards the silent hop, retransmissions included"
            )
            print()
            print("  constraint: the application's no-answer give-up is not what ends the call")
            if unreachable.gave_up and unreachable.armed_timerb > 0:
                print(
                    f"    after the application released all {unreachable.released} calls, "
                    f"{unreachable.armed_timerb} client transaction(s) were still armed for "
                    f"timerB = {unreachable.timerb_seconds}s (reaped later still by timerC)"
                )
            elif not unreachable.gave_up:
                print(
                    f"    the application released only {unreachable.released} of "
                    f"{unreachable.placed} calls inside the {args.unreachable_window:g}s window: "
                    "the failover hop's own no-answer timer did not fire, so the application "
                    "never gave up and the call is ended by timerB, not by the application"
                )
            else:
                print(
                    "    no armed transaction survived the application's give-up, so the "
                    "population this probe claims to measure was not observed"
                )
            print(
                "    constraint: the armed population scales with the burst — each call leaves "
                "one armed transaction per hop the rule set tries, so a burst of N calls "
                "against H hops leaves up to N*H transactions and their timers in the process "
                "for timerB = "
                f"{unreachable.timerb_seconds if unreachable.timerb_seconds is not None else '-'}"
                "s, whatever the application decided"
            )
            print(
                "    constraint: retransmission continues towards a silent hop — timerA "
                "doubles its interval and only timerB stops it, so a silent peer multiplies "
                "the traffic a burst generates"
            )
            print()
            results.append(unreachable_ok)
        finally:
            silent_chain.stop()

    print("--- verdict --------------------------------------------------------")
    print(f"control: one call completes through both B2BUAs : {'OK' if control_ok else 'FAILED'}")
    if args.skip_unreachable:
        print("unreachable-hop population observed            : SKIPPED")
    else:
        print(
            f"unreachable-hop population observed            : "
            f"{'OK' if unreachable_ok else 'FAILED'}"
        )
    if degradation_level is not None:
        print(
            f"degradation found at offered level             : {degradation_level} "
            "(a finding, not a failure)"
        )
    else:
        print("degradation found within the configured levels : none")
    print(
        "no calls-per-second and no latency figure is published by this probe (plan "
        "section 8 item 1, D10)"
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
