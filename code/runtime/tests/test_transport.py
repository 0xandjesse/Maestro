import os, sys
from aiohttp.test_utils import AioHTTPTestCase
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maestro_transport import MaestroTransport

class TestMaestroTransport(AioHTTPTestCase):
    async def get_application(self):
        self.transport = MaestroTransport({
            "agentId":"test-agent","port":3844,
            "hermesApiUrl":"http://127.0.0.1:8642",
            "hermesApiKey":"test-key","conversation":"test",
            "registryPath":"/tmp/test_registry.json","version":"3.2",
        })
        async def _noop(*a, **k):
            pass
        self.transport._process_message = _noop
        return self.transport.app
    async def test_handle_message_dict_content(self):
        payload = {
            "id":"msg-001","type":"direct",
            "sender":{"agentId":"proteus"},
            "content":{"task":"hello"},
            "timestamp":1715779200000,"version":"3.2",
        }
        resp = await self.client.request("POST","/message",json=payload)
        self.assertEqual(resp.status,200)
        data = await resp.json()
        self.assertTrue(data.get("accepted"))
    async def test_format_prompt_coerces_dict(self):
        msg = {
            "sender":{"agentId":"proteus"},
            "content":{"task":"hello"},
            "type":"direct",
        }
        prompt = self.transport.hermes._format_prompt(msg,agent_id="soldier")
        self.assertIsInstance(prompt,str)
        self.assertIn("task",prompt)
