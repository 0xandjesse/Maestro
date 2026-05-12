"""Tests for persistent message queue."""
import pytest
import tempfile
import time

from maestro_sdk.storage.queue import MessageQueue, QueuedMessage

@pytest.fixture
def queue():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    q = MessageQueue(path)
    yield q
    import os
    os.unlink(path)

@pytest.fixture
def sample_msg():
    return QueuedMessage(
        id="msg-1",
        sender_agent_id="alice",
        recipient_agent_id="bob",
        msg_type="direct",
        content="hello",
        headers="{}",
        status="pending",
        attempts=0,
        created_at=time.time(),
        updated_at=time.time(),
        next_attempt_at=None,
        last_error=None,
    )

def test_enqueue_and_get(queue, sample_msg):
    assert queue.enqueue(sample_msg)
    found = queue.get_by_id("msg-1")
    assert found is not None
    assert found.content == "hello"

def test_mark_delivered(queue, sample_msg):
    queue.enqueue(sample_msg)
    queue.mark_delivered("msg-1")
    found = queue.get_by_id("msg-1")
    assert found.status == "delivered"
    assert found.attempts == 0  # mark_delivered does NOT increment attempts

def test_mark_failed_with_retry(queue, sample_msg):
    queue.enqueue(sample_msg)
    queue.mark_failed("msg-1", "timeout", next_attempt=time.time() + 10)
    found = queue.get_by_id("msg-1")
    assert found.status == "failed"
    pending = queue.get_pending()
    assert len(pending) == 0  # next_attempt in future


def test_mark_retry_and_get_pending(queue, sample_msg):
    queue.enqueue(sample_msg)
    queue.mark_failed("msg-1", "timeout", next_attempt=time.time() + 10)
    # After mark_retry with next_attempt in past, should be pending again
    queue.mark_retry("msg-1", time.time() - 1)
    pending = queue.get_pending()
    assert len(pending) == 1
    assert pending[0].status == "pending"

def test_get_pending(queue, sample_msg):
    sample_msg.next_attempt_at = time.time() - 1
    queue.enqueue(sample_msg)
    pending = queue.get_pending()
    assert len(pending) == 1
    assert pending[0].id == "msg-1"
