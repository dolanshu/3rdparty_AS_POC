"""Tests for P12 REST API surface — /load/* endpoints + /ws/pool feed.

Uses FastAPI's TestClient; no actual sippy or network needed.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from tools.call_load_generator import (
    CallModel,
    CallPool,
    PoolConfig,
    build_generator_app,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Build a full app backed by a real CallPool but with a FakeUac
# ---------------------------------------------------------------------------


class _FakeUac:
    """Stub Uac that never actually sends SIP."""

    def __init__(self) -> None:
        self.spawned: list = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def send_invite(self, **kwargs) -> None:
        self.spawned.append(kwargs)


@pytest.fixture
def pool_and_app():
    """Return (CallPool, FastAPI app, TestClient)."""
    config = PoolConfig(
        target_concurrency=3,
        call_rate=10.0,
        enabled_call_types=frozenset(CallModel.ALL_TYPES),
        topology="chained",
    )
    uac = _FakeUac()
    pool = CallPool(config, mock_uac=uac)

    def getter() -> dict:
        return pool.snapshot()

    def controller(action: str, new_config: PoolConfig | None) -> dict:
        if action == "start":
            asyncio.create_task(pool.start())
            return {"started": True}
        elif action == "stop":
            asyncio.create_task(pool.stop())
            return {"stopped": True, "active_calls": pool.active_count()}
        elif action == "config" and new_config is not None:
            asyncio.create_task(pool.set_config(new_config))
            return {"configured": True}
        return {}

    app = build_generator_app(pool_state_getter=getter, pool_controller=controller)
    return pool, app


@pytest.fixture
def client(pool_and_app):
    _, app = pool_and_app
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /load/status
# ---------------------------------------------------------------------------


def test_get_status_keys(client):
    resp = client.get("/load/status")
    assert resp.status_code == 200
    body = resp.json()
    expected_keys = {
        "active_calls",
        "target_concurrency",
        "call_rate",
        "binding_constraint",
        "enabled_call_types",
        "rate_budget_remaining",
        "topology",
        "ingress_port",
    }
    assert expected_keys <= set(body.keys())
    assert body["target_concurrency"] == 3
    assert body["call_rate"] == 10.0
    assert body["binding_constraint"] in ("concurrency", "rate")


# ---------------------------------------------------------------------------
# PUT /load/config
# ---------------------------------------------------------------------------


def test_put_config_valid(client):
    resp = client.put(
        "/load/config",
        json={
            "target_concurrency": 15,
            "call_rate": 3.0,
            "enabled_call_types": ["T1", "T2", "T5", "F1", "F2"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "configured"
    assert body["config"]["target_concurrency"] == 15


def test_put_config_rejects_out_of_range(client):
    resp = client.put(
        "/load/config",
        json={
            "target_concurrency": 0,  # invalid
            "call_rate": 3.0,
            "enabled_call_types": ["T1"],
        },
    )
    assert resp.status_code == 422


def test_put_config_rejects_f_types_in_simple_topology(client):
    resp = client.put(
        "/load/config",
        json={
            "target_concurrency": 10,
            "call_rate": 3.0,
            "enabled_call_types": ["T1", "F1"],
            "topology": "simple",
        },
    )
    assert resp.status_code == 400
    assert "not valid for topology" in resp.json()["detail"]


def test_put_config_rejects_unknown_call_type(client):
    resp = client.put(
        "/load/config",
        json={
            "target_concurrency": 10,
            "call_rate": 3.0,
            "enabled_call_types": ["T1", "INVALID_TYPE"],
        },
    )
    # PoolConfig raises ValueError → our handler returns 400 Bad Request
    assert resp.status_code == 400
    assert "Unknown call types" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /load/start + POST /load/stop
# ---------------------------------------------------------------------------


def test_post_start(client):
    resp = client.post("/load/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_post_stop(client):
    resp = client.post("/load/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
