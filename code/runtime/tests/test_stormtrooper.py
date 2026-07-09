"""test_stormtrooper.py — exercise the transport layer from stormtrooper agent perspective."""

import os, sys, json, asyncio
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maestro_transport import MaestroTransport, HermesClient

TMP_BB = "/tmp/test_bb_stormtrooper"
os.makedirs(TMP_BB, exist_ok=True)
for f in os.listdir(TMP_BB):
    os.remove(os.path.join(TMP_BB, f))

CONFIG = {
    "agentId": "stormtrooper",
    "port": 38444,
    "hermesApiUrl": "http://127.0.0.1:8642",
    "hermesApiKey": "test",
    "conversation": "storm-channel",
    "registryPath": "/tmp/test_registry_stormtrooper.json",
    "version": "3.2",
}

# Patch HermesClient.health_check so transport starts without a real gateway.
async def _mock_health(self):
    return True

HermesClient.health_check = _mock_health


def test_transport_instantiation():
    t = MaestroTransport(CONFIG)
    assert t.agent_id == "stormtrooper"
    assert t.port == 38444
    assert hasattr(t, "memory_service")
    print("PASS instantiation")


def test_memory_write_read_stormtrooper():
    t = MaestroTransport(CONFIG)
    # Use the transport's own memory helper if available, else raw hermes_memory
    try:
        from hermes_memory import memory_write, memory_read
    except ImportError:
        from maestro_transport import hermes_memory as hm
        memory_write = hm.memory_write
        memory_read = hm.memory_read

    r = memory_write("stormtrooper", "mission alpha", tags=["mission"], importance=0.9)
    assert r["ok"]
    mid = r["memory_id"]

    r2 = memory_read("stormtrooper", mid, requester="stormtrooper")
    assert r2["ok"]
    assert r2["memory"]["content"] == "mission alpha"
    assert r2["memory"]["access_count"] == 1
    print("PASS memory_write_read")


def test_officer_access_stormtrooper_memory():
    from hermes_memory import memory_write, memory_read
    r = memory_write("stormtrooper", "classified", tags=["ops"], importance=0.8)
    mid = r["memory_id"]

    # songbird (officer) can read if shared_with ["*"]
    r2 = memory_read("stormtrooper", mid, requester="songbird")
    assert r2["ok"]

    # non-officer evil_agent should NOT have access
    r3 = memory_write("stormtrooper", "super secret", tags=["ops"], shared_with=["stormtrooper"])
    mid2 = r3["memory_id"]
    r4 = memory_read("stormtrooper", mid2, requester="evil_agent")
    assert not r4["ok"]
    assert "access_denied" in r4["reason"]
    print("PASS officer_access")


def test_search_delete_stormtrooper():
    from hermes_memory import memory_write, memory_search, memory_delete
    for i in range(3):
        memory_write("stormtrooper", f"log entry {i}", tags=["log"])

    res = memory_search("stormtrooper", query="log entry 1", requester="stormtrooper")
    assert res["ok"]
    assert len(res["results"]) >= 1

    # Delete one by memory_id
    d = memory_delete("stormtrooper", memory_id=res["results"][0]["id"], requester="stormtrooper")
    assert d["ok"]
    print("PASS search_delete")


def test_transport_config_roundtrip():
    t = MaestroTransport(CONFIG)
    dumped = json.dumps(t.config)
    loaded = json.loads(dumped)
    assert loaded["agentId"] == "stormtrooper"
    assert loaded["port"] == 38444
    print("PASS config_roundtrip")


if __name__ == "__main__":
    test_transport_instantiation()
    test_memory_write_read_stormtrooper()
    test_officer_access_stormtrooper_memory()
    test_search_delete_stormtrooper()
    test_transport_config_roundtrip()
    print("\nAll stormtrooper unit tests PASSED")
