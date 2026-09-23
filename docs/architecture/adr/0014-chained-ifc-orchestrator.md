# ADR-0014: Chained AS topology — iFC-orchestrated mock (P9b)

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** project maintainer
- **Supersedes:** ADR-0008 decision 1 (peer-to-peer `FRAUD_SBC_PEER_* → AS-2`)
- **Related:** `docs/chained-topology-plan.md` · `docs/architecture/hld.md` section 9 ·
  ADR-0008 (historical) · REQ-F-025…REQ-F-028 · REQ-NF-016…REQ-NF-018

## Context

ADR-0008 decision 1 wired AS-1's `FRAUD_SBC_PEER_*` at AS-2's listen address. That
trunk-to-trunk shortcut contradicts the IMS model: external ASs are reached only when
S-CSCF applies iFC and the operator S-SBC delivers a trunk INVITE. P9b corrects the POC mock.

## Decision

### 1. AS instances never communicate directly

Chain order lives in `ims_mock/chain_config.py`. `*_SBC_PEER_*` remains the fallback when
the trunk INVITE carries no `Route`, pointing at the S-SBC **return** port only.

### 2. S-SBC return 透传 drives iFC #2

When AS-1's outbound INVITE reaches the S-SBC return side, an in-process callback notifies
the orchestrator, which triggers a **new** trunk INVITE to AS-2 (Call-ID `Z ≠ X`).

### 3. Terminating path is S-CSCF → P-CSCF → UAS

The called-party UAS is **not** hung off the S-SBC return port. `ims_mock/pcscf_relay.py`
forwards AS-2's outbound INVITE toward `terminating_uas` after the second 透传.

### 4. Four AS-leg Call-ID values on the allow path

| Leg | Typical Call-ID |
| --- | --- |
| S-SBC → AS-1 trunk | `X` |
| AS-1 outbound → return | `X-b2b_1` |
| S-SBC → AS-2 trunk (iFC #2) | `Z` |
| AS-2 outbound → return | `Z-b2b_1` |

### 5. AS-1 legs stay up until subscriber BYE (D8)

iFC #2 fires on AS-1 outbound 透传, not after BYE on AS-1.

### 6. P10 friction narrative

The friction P10 inherits is that the POC requires an **IMS-side orchestrator mock**; neither
AS knows about the chain.

## Consequences

- `src/ims_mock/` holds orchestrator, P-CSCF relay and terminating UAS.
- `s_sbc_mock` return side supports passthrough callbacks (section 3.4 of the plan).
- `tools/demo_chained_call.py`, `chained_as_probe.py` and `chained_pair_factory` use the
  new stack; `FRAUD_SBC_PEER_PORT=AS_TRANS_SIP` is removed.
