import asyncio
import sys
sys.path.insert(0, "/home/andjesse/maestro-transport")
import maestro_transport as mt

# Patch health check so server starts without a real gateway
async def _mock_health_check(self):
    return True
mt.HermesClient.health_check = _mock_health_check

config = mt.load_config("test_transport.json")
transport = mt.MaestroTransport(config)

async def main():
    runner = mt.web.AppRunner(transport.app)
    await runner.setup()
    await mt.web.TCPSite(runner, "0.0.0.0", config["port"]).start()
    print(f"Test server running on port {config['port']}")
    while True:
        await asyncio.sleep(3600)

asyncio.run(main())
