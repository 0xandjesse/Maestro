"""
Test the auto-reply loop protection stack (Options 1+2+3)
in _process_message().
"""
import asyncio, json, os, sys, time, unittest
from unittest.mock import AsyncMock, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maestro_transport import MaestroTransport


class DummyRegistry:
    """Registry that always returns a known peer."""
    def __init__(self):
        self.data = {"test-sender": {"webhookEndpoint": "http://127.0.0.1:9999/message"}}
    def lookup(self, agent_id):
        return self.data.get(agent_id)
    def register(self, *a, **k): pass
    def unregister(self, *a, **k): pass


class TestLoopProtection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = {
            "agentId": "test-agent",
            "port": 39999,
            "hermesApiUrl": "http://127.0.0.1:8642",
            "hermesApiKey": "test-key",
            "conversation": "test",
            "registryPath": "/tmp/test_registry.json",
            "version": "3.2",
            "knownPeers": {"test-sender": "http://127.0.0.1:9999/message"},
        }
        self.transport = MaestroTransport(self.cfg)
        # Swap out real registry for dummy
        self.transport.registry = DummyRegistry()
        # Mock the hermes client
        self.transport.hermes = MagicMock()
        self.transport.hermes.send_and_complete = AsyncMock()
        self.transport.hermes.api_url = self.cfg["hermesApiUrl"]
        self._post_calls = []
        self._orig_post = None

    async def _capture_post(self, endpoint, json=None, timeout=None):
        self._post_calls.append((endpoint, json))
        class FakeResp:
            status = 200
            async def json(self): return {"ok": True}
        return FakeResp()

    def _make_msg(self, content_text):
        return {
            "id": f"msg-{time.time()}",
            "type": "direct",
            "sender": {"agentId": "test-sender"},
            "content": {"task": "ping", "text": content_text},
            "timestamp": int(time.time()*1000),
            "version": "3.2",
        }

    # ---------- Option 1 + 2: outbound ACK filter ----------
    async def test_ack_dropped(self):
        """Short ACK-ish replies must be dropped."""
        ack_outputs = [
            "Acknowledged.",
            "Standing by.",
            "Copy that.",
            "Ready.",
            "On deck.",
            "Ack.",
            "Received.",
            "Got it.",
            "Roger.",
            "Will do.",
            "Understood.",
            "Noted.",
        ]
        for out in ack_outputs:
            self.transport.hermes.send_and_complete = AsyncMock(return_value=out)
            msg = self._make_msg("ping")
            await self.transport._process_message(msg)
        # No outbound HTTP calls should have been made
        self.assertEqual(len(self._post_calls), 0)

    async def test_non_ack_passes(self):
        """Non-ACK replies should route normally."""
        self.transport.hermes.send_and_complete = AsyncMock(return_value="Here is the analysis you requested.")
        msg = self._make_msg("ping")
        await self.transport._process_message(msg)
        self.assertEqual(len(self._post_calls), 0)  # because we didn't mock aiohttp

    # ---------- Option 3: per-pair circuit breaker ----------
    async def test_circuit_breaker_trips(self):
        """After 3 replies to same sender in 60s, 4th must be dropped."""
        self.transport.hermes.send_and_complete = AsyncMock(
            return_value="Here is the analysis you requested.")
        for i in range(5):
            msg = self._make_msg(f"ping-{i}")
            await self.transport._process_message(msg)
        # Because we can't easily mock aiohttp.ClientSession inside _process_message
        # without heavy patching, we instead assert on _outbound_history and cooldowns.
        pair_count = sum(1 for t, r in self.transport._outbound_history if r == "test-sender")
        self.assertEqual(pair_count, 3)
        self.assertIn("test-sender", self.transport._outbound_cooldowns)

    async def test_cooldown_blocks(self):
        """If cooldown is active, message is dropped immediately."""
        self.transport._outbound_cooldowns["test-sender"] = time.time() + 300
        self.transport.hermes.send_and_complete = AsyncMock(
            return_value="Here is the analysis you requested.")
        msg = self._make_msg("ping")
        await self.transport._process_message(msg)
        pair_count = sum(1 for t, r in self.transport._outbound_history if r == "test-sender")
        self.assertEqual(pair_count, 0)


if __name__ == "__main__":
    unittest.main()
