import json
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

import maestro_transport as mt

# Patch HermesClient.health_check so MaestroTransport can instantiate without a real gateway
async def _mock_health_check(self):
    return True

mt.HermesClient.health_check = _mock_health_check


@pytest.fixture
def tmp_mem_dir(monkeypatch, tmp_path):
    """Redirect all MemoryService blackboard files into tmp_path."""
    original_init = mt.MemoryService.__init__
    def _patched_init(self, bb_root):
        self.bb_root = tmp_path
        self.bb_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mt.MemoryService, "__init__", _patched_init)
    return tmp_path


@pytest_asyncio.fixture
async def client(tmp_mem_dir):
    config = {
        "agentId": "test-agent",
        "port": 39999,
        "hermesApiUrl": "http://127.0.0.1:8642",
        "hermesApiKey": "test",
        "conversation": "test",
        "version": "3.2",
        "registryPath": str(tmp_mem_dir / "registry.json"),
    }
    transport = mt.MaestroTransport(config)
    server = TestServer(transport.app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_write_and_read(client):
    resp = await client.post("/maestro/memory/write", json={
        "agent_id": "proteus",
        "content": "test payload",
        "tags": ["t1"],
        "shared_with": ["*"],
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    mid = data["memory_id"]

    resp2 = await client.post("/maestro/memory/read", json={
        "agent_id": "proteus",
        "memory_id": mid,
        "requester": "proteus",
    })
    assert resp2.status == 200
    d2 = await resp2.json()
    assert d2["memory"]["content"] == "test payload"
    assert d2["memory"]["access_count"] == 1
    assert d2["memory"]["size_bytes"] > 0


@pytest.mark.asyncio
async def test_access_control_denied_and_allowed(client):
    # Private memory (no shared_with)
    resp = await client.post("/maestro/memory/write", json={
        "agent_id": "proteus",
        "content": "secret",
        "shared_with": [],
    })
    assert resp.status == 200
    mid = (await resp.json())["memory_id"]

    # songbird cannot read private memory
    resp2 = await client.post("/maestro/memory/read", json={
        "agent_id": "proteus",
        "memory_id": mid,
        "requester": "songbird",
    })
    assert resp2.status == 403
    d2 = await resp2.json()
    assert d2["reason"] == "access_denied"

    # public memory via ["*"]
    resp3 = await client.post("/maestro/memory/write", json={
        "agent_id": "proteus",
        "content": "public info",
        "shared_with": ["*"],
    })
    mid_pub = (await resp3.json())["memory_id"]

    resp4 = await client.post("/maestro/memory/read", json={
        "agent_id": "proteus",
        "memory_id": mid_pub,
        "requester": "songbird",
    })
    assert resp4.status == 200

    # unauthorized requester
    resp5 = await client.post("/maestro/memory/read", json={
        "agent_id": "proteus",
        "memory_id": mid_pub,
        "requester": "evil_agent",
    })
    assert resp5.status == 403
    d5 = await resp5.json()
    assert d5["reason"] == "unauthorized_requester"


@pytest.mark.asyncio
async def test_search_and_ttl_expiry_and_delete(client):
    # Write two memories: one expires immediately, one lives forever
    resp1 = await client.post("/maestro/memory/write", json={
        "agent_id": "proteus",
        "content": "architecture decision",
        "tags": ["arch"],
        "importance": 0.9,
        "ttl_seconds": 0,   # expires immediately
    })
    mid1 = (await resp1.json())["memory_id"]

    resp2 = await client.post("/maestro/memory/write", json={
        "agent_id": "proteus",
        "content": "deployment strategy",
        "tags": ["ops"],
        "importance": 0.7,
    })
    mid2 = (await resp2.json())["memory_id"]

    # Search for "architecture" — expired entry must be skipped
    resp3 = await client.post("/maestro/memory/search", json={
        "agent_id": "proteus",
        "query": "architecture",
        "requester": "proteus",
    })
    d3 = await resp3.json()
    assert d3["total"] == 0
    ids = [r["id"] for r in d3["results"]]
    assert mid1 not in ids

    # List should show only the live memory
    resp4 = await client.post("/maestro/memory/list", json={
        "agent_id": "proteus",
        "requester": "proteus",
    })
    d4 = await resp4.json()
    assert d4["count"] == 1
    assert d4["memories"][0]["id"] == mid2

    # Delete live memory
    resp5 = await client.post("/maestro/memory/delete", json={
        "agent_id": "proteus",
        "memory_id": mid2,
        "requester": "proteus",
    })
    assert resp5.status == 200
    d5 = await resp5.json()
    assert d5["ok"] is True

    # Verify gone
    resp6 = await client.post("/maestro/memory/read", json={
        "agent_id": "proteus",
        "memory_id": mid2,
        "requester": "proteus",
    })
    assert resp6.status == 404
    d6 = await resp6.json()
    assert d6["reason"] == "not_found"


@pytest.mark.asyncio
async def test_search_tags_and_importance_sort(client):
    for i in range(3):
        await client.post("/maestro/memory/write", json={
            "agent_id": "proteus",
            "content": f"memory {i}",
            "tags": ["arch"] if i != 1 else ["ops"],
            "importance": 0.9 - i * 0.1,
            "shared_with": ["*"],
        })

    resp = await client.post("/maestro/memory/search", json={
        "agent_id": "proteus",
        "tags": ["arch"],
        "min_importance": 0.75,
        "requester": "songbird",
        "limit": 5,
    })
    assert resp.status == 200
    d = await resp.json()
    assert d["total"] == 1   # arch tag + importance >= 0.75 (only 0.9 qualifies)
    assert all("arch" in r["tags"] for r in d["results"])
    assert d["results"][0]["importance"] >= 0.75


@pytest.mark.asyncio
async def test_message_type_routing(client, tmp_mem_dir):
    """Ensure MEMORY_WRITE / MEMORY_READ / MEMORY_SEARCH / MEMORY_DELETE / MEMORY_LIST
    message types are accepted by the transport message endpoint."""
    msg = {
        "id": "test-msg-001",
        "type": "MEMORY_WRITE",
        "sender": {"agentId": "proteus"},
        "content": {
            "agent_id": "proteus",
            "content": "msg routed memory",
            "tags": ["msg"],
        },
    }
    resp = await client.post("/message", json=msg)
    assert resp.status == 200
    d = await resp.json()
    assert d["accepted"] is True
    # Memory should now exist
    mem_path = tmp_mem_dir / "memory_proteus.json"
    assert mem_path.exists()
    data = json.loads(mem_path.read_text())
    assert any(v["content"] == "msg routed memory" for v in data.values())
