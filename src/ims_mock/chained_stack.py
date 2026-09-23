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

"""Wire AS-1, AS-2, S-SBC mock, orchestrator and terminating UAS for chained mode."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sippy.CCEvents import CCEventConnect, CCEventDisconnect, CCEventRing
from sippy.Core.EventDispatcher import ED2
from sippy.SipHeader import SipHeader
from sippy.SipLogger import SipLogger
from sippy.SipTransactionManager import SipTransactionManager
from sippy.Time.Timeout import Timeout

from as_app.sip_adapter import PASSTHROUGH_HEADERS
from ims_mock.chain_config import ChainConfig
from ims_mock.orchestrator import OrchestratorFsm, OrchestratorState
from ims_mock.pcscf_relay import PcscfRelay
from ims_mock.terminating_uas import TerminatingUas
from s_sbc_mock.uac import CallOutcome, CallScenario, TrunkUac
from s_sbc_mock.uas import ReturnUas

_DEFAULT_LAZY_SCENARIO = CallScenario(
    name="load-gen",
    calling_number="+8613800138000",
    called_number="+8613800138000",
    ring_seconds=0.05,
    talk_seconds=0.05,
)

__all__ = ["ChainedImsStack", "ChainedOrchestrator", "ExternalRuntimePorts"]

_LOGGER = logging.getLogger(__name__)

POLL_SECONDS = 0.02
CALL_TIMEOUT_SECONDS = 15.0
_B2B_SUFFIX = "-b2b_1"


@dataclass
class CallSession:
    """Per-subscriber-call orchestrator state."""

    subscriber_call_id: str
    scenario: CallScenario
    fsm: OrchestratorFsm = field(default_factory=OrchestratorFsm)
    as1_return_ua: Any = None
    as2_return_ua: Any = None
    as2_trunk_call_id: str | None = None


class ChainedOrchestrator:
    """S-CSCF orchestrator: iFC triggers and return-side 透传 bridging."""

    def __init__(self, stack: ChainedImsStack) -> None:
        """Attach to a :class:`ChainedImsStack`."""
        self.stack = stack
        self._sessions: dict[str, CallSession] = {}

    def begin_session(self, scenario: CallScenario, subscriber_call_id: str) -> None:
        """Record a new subscriber call before iFC #1 is sent."""
        session = CallSession(subscriber_call_id=subscriber_call_id, scenario=scenario)
        session.fsm.on_subscriber_invite()
        session.fsm.on_ifc1_sent()
        self._sessions[subscriber_call_id] = session

    def on_return_invite(self, request: Any, ua: Any, _leg: str) -> None:
        """Handle AS outbound INVITE on the S-SBC return port (透传)."""
        call_id = str(request.getHFBody("call-id"))
        session = self._session_for_return(call_id)
        if session.fsm.state == OrchestratorState.AS1_AWAIT_OUTBOUND:
            session.as1_return_ua = ua
            session.fsm.on_as1_outbound_passthrough()
            hop2 = self.stack.chain.hops[1]
            as2_trunk = self.stack.mock_uac.send_trunk_invite(
                session.scenario, hop2.host, hop2.port, name_suffix="-ifc2"
            )
            session.as2_trunk_call_id = as2_trunk
            session.fsm.on_ifc2_sent()
            return
        if session.fsm.state == OrchestratorState.AS2_AWAIT_OUTBOUND:
            session.as2_return_ua = ua
            session.fsm.on_as2_outbound_passthrough()
            called = str(request.getRURI().username)
            body = request.getBody()
            sdp = "" if body is None else str(body).strip()
            calling = _calling_from_pai(request)
            extra_headers = _passthrough_headers(request)
            self.stack.pcscf.forward_invite(
                called,
                sdp,
                session_id=session.subscriber_call_id,
                calling_number=calling,
                extra_headers=extra_headers,
                on_provisional=lambda code, reason, sid=session.subscriber_call_id: (
                    self._relay_provisional(sid, code, reason)
                ),
                on_final=lambda code, reason, body, sid=session.subscriber_call_id: (
                    self._relay_final(sid, code, reason, body)
                ),
                on_disconnect=lambda sid=session.subscriber_call_id: self._relay_disconnect(sid),
            )
            return
        raise RuntimeError(
            f"unexpected return INVITE call_id={call_id} in state {session.fsm.state}"
        )

    def _lazy_subscriber_session(self, subscriber_call_id: str) -> CallSession:
        """Register a subscriber call placed by an external UAC (P14 load generator)."""
        session = CallSession(
            subscriber_call_id=subscriber_call_id,
            scenario=_DEFAULT_LAZY_SCENARIO,
        )
        session.fsm.state = OrchestratorState.AS1_AWAIT_OUTBOUND
        self._sessions[subscriber_call_id] = session
        return session

    def _session_for_return(self, return_call_id: str) -> CallSession:
        parent = _parent_call_id(return_call_id)
        for session in self._sessions.values():
            if session.fsm.state == OrchestratorState.AS1_AWAIT_OUTBOUND:
                if parent == session.subscriber_call_id:
                    return session
            if session.fsm.state == OrchestratorState.AS2_AWAIT_OUTBOUND:
                if session.as2_trunk_call_id == parent:
                    return session
        if return_call_id.endswith(_B2B_SUFFIX):
            return self._lazy_subscriber_session(parent)
        raise RuntimeError(f"no session for return Call-ID {return_call_id}")

    def _session(self, subscriber_call_id: str) -> CallSession:
        session = self._sessions.get(subscriber_call_id)
        if session is None:
            raise RuntimeError(f"unknown subscriber Call-ID {subscriber_call_id}")
        return session

    def _relay_provisional(self, subscriber_call_id: str, code: int, reason: str) -> None:
        session = self._session(subscriber_call_id)
        event = CCEventRing((code, reason, None))
        if session.as2_return_ua is not None:
            session.as2_return_ua.recvEvent(event)
        if session.as1_return_ua is not None:
            session.as1_return_ua.recvEvent(event)

    def _relay_final(
        self, subscriber_call_id: str, code: int, reason: str, body: Any
    ) -> None:
        session = self._session(subscriber_call_id)
        event = CCEventConnect((code, reason, body))
        if session.as2_return_ua is not None:
            session.as2_return_ua.recvEvent(event)
        if session.as1_return_ua is not None:
            session.as1_return_ua.recvEvent(event)
        session.fsm.on_dialog_active()

    def _relay_disconnect(self, subscriber_call_id: str) -> None:
        session = self._session(subscriber_call_id)
        event = CCEventDisconnect()
        if session.as2_return_ua is not None:
            session.as2_return_ua.recvEvent(event)
        if session.as1_return_ua is not None:
            session.as1_return_ua.recvEvent(event)
        if session.fsm.state in (OrchestratorState.ACTIVE, OrchestratorState.TERMINATING):
            session.fsm.on_bye()
        self._sessions.pop(subscriber_call_id, None)


def _parent_call_id(call_id: str) -> str:
    """Strip one B2BUA ``-b2b_1`` suffix."""
    if call_id.endswith(_B2B_SUFFIX):
        return call_id[: -len(_B2B_SUFFIX)]
    return call_id


def _passthrough_headers(request: Any) -> tuple[Any, ...]:
    """Build extra headers for the P-CSCF relay from an AS outbound INVITE."""
    headers: list[Any] = []
    for name in PASSTHROUGH_HEADERS:
        if request.countHFs(name) == 0:
            continue
        value = str(request.getHFBody(name)).strip()
        headers.append(SipHeader(s=f"{name}: {value}"))
    return tuple(headers)


def _calling_from_pai(request: Any) -> str | None:
    """Extract the E.164 user part from ``P-Asserted-Identity``."""
    if request.countHFs("p-asserted-identity") == 0:
        return None
    raw = str(request.getHFBody("p-asserted-identity")).strip()
    if raw.startswith("<") and "@" in raw:
        user = raw.split(":", 1)[-1].split("@", 1)[0].rstrip(">")
        return user
    return raw


@dataclass(frozen=True)
class ExternalRuntimePorts:
    """UDP ports for a multi-process chained demo (P14)."""

    as1_port: int
    as2_port: int
    return_port: int
    forward_port: int
    terminating_port: int
    pcscf_port: int

    @property
    def ingress_port(self) -> int:
        """Port the load generator uses as subscriber ingress (AS-1 trunk)."""
        return self.as1_port


@dataclass
class ChainedImsStack:
    """Full iFC-orchestrated chain on loopback UDP."""

    as1: Any | None
    as2: Any | None
    mock_uac: TrunkUac
    mock_uas: ReturnUas
    terminating: TerminatingUas
    pcscf: PcscfRelay
    orchestrator: ChainedOrchestrator
    chain: ChainConfig
    as1_port: int
    as2_port: int
    return_port: int
    forward_port: int
    terminating_port: int
    pcscf_port: int
    as1_messages: Any = None
    as2_messages: Any = None
    _transaction_managers: list[Any] = field(default_factory=list, repr=False)
    _stopped: bool = field(default=False, repr=False)

    def place_call(self, scenario: CallScenario) -> str:
        """Place a subscriber call (iFC #1 trunk INVITE to AS-1).

        Args:
            scenario: Call to place.

        Returns:
            Subscriber-side Call-ID.
        """
        call_id = self.mock_uac.place_call(scenario)
        self.orchestrator.begin_session(scenario, call_id)
        return call_id

    def outcome_for(self, call_id: str) -> CallOutcome | None:
        """Return the trunk-side outcome for a subscriber Call-ID."""
        return self.mock_uac.outcome_for(call_id)

    def run_until(self, predicate: Any, timeout_seconds: float = CALL_TIMEOUT_SECONDS) -> bool:
        """Drive ``ED2`` until ``predicate()`` is true."""
        import time

        deadline = time.monotonic() + timeout_seconds
        state = {"done": predicate()}

        def poll() -> None:
            if predicate() or time.monotonic() >= deadline:
                state["done"] = predicate()
                ED2.breakLoop()

        timer = Timeout(poll, POLL_SECONDS, -1)
        try:
            ED2.loop(timeout=timeout_seconds)
        finally:
            timer.cancel()
        return bool(state["done"])

    def start(self) -> None:
        """Bind every UDP side and register transaction managers."""
        logger = SipLogger("chained-ims")
        return_config = self.mock_uas.build_global_config(logger)
        return_tm = SipTransactionManager(return_config, self.mock_uas.recv_request)
        return_config["_sip_tm"] = return_tm

        forward_config = self.mock_uac.build_global_config(logger)
        forward_tm = SipTransactionManager(forward_config)
        forward_config["_sip_tm"] = forward_tm

        term_config = self.terminating.build_global_config(logger)
        term_tm = SipTransactionManager(term_config, self.terminating.recv_request)
        term_config["_sip_tm"] = term_tm

        pcscf_config = self.pcscf.build_global_config(logger)
        pcscf_tm = SipTransactionManager(pcscf_config)
        pcscf_config["_sip_tm"] = pcscf_tm

        self._transaction_managers = [return_tm, forward_tm, term_tm, pcscf_tm]
        if self.as1 is not None:
            self.as1.start()
        if self.as2 is not None:
            self.as2.start()

    def stop(self) -> None:
        """Release ports and stacks."""
        if self._stopped:
            return
        if self.as2 is not None:
            self.as2.stop()
        if self.as1 is not None:
            self.as1.stop()
        for manager in self._transaction_managers:
            manager.shutdown()
        self._transaction_managers = []
        self._stopped = True

    @classmethod
    def build_external(
        cls,
        *,
        as1_port: int,
        as2_port: int,
        return_port: int,
        forward_port: int,
        terminating_port: int,
        pcscf_port: int,
        bind_address: str = "127.0.0.1",
    ) -> ChainedImsStack:
        """Construct a chain wired to **external** AS processes (P14).

        Args:
            as1_port: Anti-fraud AS SIP listen port.
            as2_port: Translation AS SIP listen port.
            return_port: S-SBC return / passthrough port both AS peer to.
            forward_port: Local bind port for orchestrator trunk UAC.
            terminating_port: Called-party UAS port.
            pcscf_port: P-CSCF relay local port.
            bind_address: Loopback address for every bind.

        Returns:
            A stack that must be :meth:`start`ed and driven with ``ED2.loop()``.
        """
        return cls.build(
            as1=None,
            as2=None,
            as1_port=as1_port,
            as2_port=as2_port,
            return_port=return_port,
            forward_port=forward_port,
            terminating_port=terminating_port,
            pcscf_port=pcscf_port,
            bind_address=bind_address,
        )

    @classmethod
    def build(
        cls,
        *,
        as1: Any | None,
        as2: Any | None,
        as1_port: int,
        as2_port: int,
        return_port: int,
        forward_port: int,
        terminating_port: int,
        pcscf_port: int,
        bind_address: str = "127.0.0.1",
        as1_messages: Any = None,
        as2_messages: Any = None,
    ) -> ChainedImsStack:
        """Construct a wired stack without starting it."""
        chain = ChainConfig.default_two_as(bind_address, as1_port, bind_address, as2_port)
        mock_uas = ReturnUas(
            bind_address,
            return_port,
            passthrough=True,
            leg_label="return",
            passthrough_callback=None,
        )
        mock_uac = TrunkUac(
            bind_address,
            as1_port,
            local_address=bind_address,
            local_port=forward_port,
            route_return_address=bind_address,
            route_return_port=return_port,
        )
        terminating = TerminatingUas(bind_address, terminating_port)
        pcscf = PcscfRelay(
            bind_address,
            terminating_port,
            local_address=bind_address,
            local_port=pcscf_port,
        )
        stack = cls(
            as1=as1,
            as2=as2,
            mock_uac=mock_uac,
            mock_uas=mock_uas,
            terminating=terminating,
            pcscf=pcscf,
            orchestrator=ChainedOrchestrator.__new__(ChainedOrchestrator),
            chain=chain,
            as1_port=as1_port,
            as2_port=as2_port,
            return_port=return_port,
            forward_port=forward_port,
            terminating_port=terminating_port,
            pcscf_port=pcscf_port,
            as1_messages=as1_messages,
            as2_messages=as2_messages,
        )
        orchestrator = ChainedOrchestrator(stack)
        stack.orchestrator = orchestrator
        mock_uas.passthrough_callback = orchestrator
        return stack
