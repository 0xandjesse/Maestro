"""HTTP server wrapper for the ConnectionBroker."""
import asyncio
import json
import logging
from typing import Optional

from aiohttp import web

from .broker import ConnectionBroker

log = logging.getLogger("maestro.server")

class MaestroServer:
    """ aiohttp server that binds the ConnectionBroker to HTTP endpoints. """

    def __init__(self, broker: ConnectionBroker, host: str = "0.0.0.0", port: int = 3844):
        self.broker = broker
        self.host = host
        self.port = port
        self.app = web.Application()
        self._setup_routes()
        self.runner: Optional[web.AppRunner] = None

    def _setup_routes(self):
        self.app.router.add_post("/message", self._handle_message)
        self.app.router.add_post("/maestro/webhook", self._handle_message)
        self.app.router.add_get("/health", self._handle_health)
        self.app.router.add_get("/connections/{connection_id}", self._handle_connection_get)

    async def _handle_message(self, request: web.Request) -> web.Response:
        try:
            message = await request.json()
        except Exception:
            return web.json_response({"accepted": False, "reason": "Invalid JSON"}, status=400)

        # Basic validation
        if not message.get("id") or not message.get("type") or not message.get("sender"):
            return web.json_response({"accepted": False, "reason": "Invalid message format"}, status=400)

        result = self.broker.handle_inbound(message)
        status = 200 if result.get("accepted") else 400
        return web.json_response(result, status=status)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "agentId": self.broker.config.agent_id,
            "platform": "hermes-agent",
            "uptime": 0,  # TODO
        })

    async def _handle_connection_get(self, request: web.Request) -> web.Response:
        cid = request.match_info["connection_id"]
        return web.json_response({"id": cid, "status": "active", "agentId": self.broker.config.agent_id})

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        log.info(f"Maestro server listening on {self.host}:{self.port}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            log.info("Maestro server stopped")
