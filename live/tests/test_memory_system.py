import os, sys, json, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maestro_transport import MemoryService

TMP_BB = "/tmp/test_blackboards"
os.makedirs(TMP_BB, exist_ok=True)
for f in os.listdir(TMP_BB):
    os.remove(os.path.join(TMP_BB, f))

svc = MemoryService(Path(TMP_BB))
AGENT = "proteus"
OFFICER = "songbird"
OTHER = "stormtrooper"

def test_write_read():
    mem_id = svc.write(AGENT, {"content": "hello", "tags": ["test"], "importance": 5})["memory_id"]
    result = svc.read(AGENT, mem_id, requester=AGENT)
    assert result["ok"]
    assert result["memory"]["content"]["content"] == "hello"
    print("PASS write_read")

def test_access_control_officer():
    mem_id = svc.write(AGENT, {"content": "secret", "tags": [], "importance": 5})["memory_id"]
    assert svc.read(AGENT, mem_id, requester=OFFICER)["ok"]
    print("PASS access_officer")

def test_access_denied():
    mem_id = svc.write(AGENT, {"content": "private"}, tags=[], importance=5, shared_with=["proteus"])["memory_id"]
    result = svc.read(AGENT, mem_id, requester=OTHER)
    assert not result["ok"]
    assert "access_denied" in result["reason"] or "forbidden" in result["reason"]
    print("PASS access_denied")

def test_ttl_expiry():
    mem_id = svc.write(AGENT, {"content": "expires fast"}, tags=[], importance=1, ttl_seconds=0.01)["memory_id"]
    time.sleep(0.05)
    result = svc.read(AGENT, mem_id, requester=AGENT)
    assert not result["ok"]
    assert "expired" in result["reason"]
    print("PASS ttl_expiry")

def test_search():
    svc.write(AGENT, {"content": "alpha bravo", "tags": ["alpha"], "importance": 3})
    svc.write(AGENT, {"content": "charlie delta", "tags": ["charlie"], "importance": 4})
    res = svc.search(AGENT, requester=AGENT, query="alpha")
    assert res["ok"]
    assert len(res["results"]) >= 1
    print("PASS search")

def test_delete():
    mem_id = svc.write(AGENT, {"content": "to delete", "tags": [], "importance": 1})["memory_id"]
    assert svc.delete(AGENT, mem_id, requester=AGENT)["ok"]
    assert not svc.read(AGENT, mem_id, requester=AGENT)["ok"]
    print("PASS delete")

def test_list():
    svc.write(AGENT, {"content": "list a", "tags": [], "importance": 1})
    svc.write(AGENT, {"content": "list b", "tags": [], "importance": 2})
    res = svc.list(AGENT, requester=AGENT)
    assert res["ok"]
    assert len(res["memories"]) >= 2
    print("PASS list")

if __name__ == "__main__":
    test_write_read()
    test_access_control_officer()
    test_access_denied()
    test_ttl_expiry()
    test_search()
    test_delete()
    test_list()
    print("\nAll memory unit tests PASSED")
