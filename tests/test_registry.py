"""Tests for persistent agent registry."""
import pytest
import tempfile
import time

from maestro_sdk.storage.registry import AgentRegistry, ContactCard

@pytest.fixture
def registry():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    r = AgentRegistry(path)
    yield r
    import os
    os.unlink(path)

@pytest.fixture
def sample_card():
    return ContactCard(
        agent_id="alice",
        wallet_address="0xabc123",
        endpoints='[{"url":"http://127.0.0.1:3844","ttl":3600,"last_seen":' + str(time.time()) + '}]',
        capabilities='["messaging","calendar"]',
        trusted_by='["bob"]',
        created_at=time.time(),
        updated_at=time.time(),
        expires_at=time.time() + 86400,
    )

def test_upsert_and_get(registry, sample_card):
    assert registry.upsert_contact(sample_card)
    found = registry.get_contact("alice")
    assert found is not None
    assert found.wallet_address == "0xabc123"

def test_list_contacts(registry, sample_card):
    registry.upsert_contact(sample_card)
    contacts = registry.list_contacts()
    assert len(contacts) == 1

def test_prune_expired(registry, sample_card):
    sample_card.expires_at = time.time() - 1
    registry.upsert_contact(sample_card)
    count = registry.prune_expired()
    assert count == 1
    found = registry.get_contact("alice")
    assert found is None
