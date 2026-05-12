"""CLI entry point for running a Maestro agent server."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from .transport.broker import ConnectionBroker, TransportConfig
from .transport.server import MaestroServer
from .plugins.manager import PluginManager
from .plugins.calendar_trigger import CalendarTriggerPlugin

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("maestro.cli")

def load_config(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def build_config(args) -> TransportConfig:
    file_config = load_config(args.config) if args.config else {}
    db_dir = Path(args.db_dir or file_config.get("dbDir", os.path.expanduser("~/.maestro/db")))
    db_dir.mkdir(parents=True, exist_ok=True)

    return TransportConfig(
        agent_id=args.agent_id or file_config.get("agentId", "maestro-agent"),
        listen_port=args.port or file_config.get("port", 3844),
        hermes_api_url=args.hermes_url or file_config.get("hermesApiUrl"),
        hermes_api_key=args.hermes_key or file_config.get("hermesApiKey"),
        db_path=str(db_dir / "messages.db"),
        registry_db_path=str(db_dir / "registry.db"),
        blackboard_db_path=str(db_dir / "blackboards.db"),
        max_retries=args.max_retries or file_config.get("maxRetries", 3),
        base_retry_delay=args.base_delay or file_config.get("baseRetryDelay", 2.0),
        max_retry_delay=args.max_delay or file_config.get("maxRetryDelay", 60.0),
    )

async def main_async():
    parser = argparse.ArgumentParser(description="Maestro Agent Server")
    parser.add_argument("--config", "-c", help="JSON config file path")
    parser.add_argument("--agent-id", "-a", help="Agent identity")
    parser.add_argument("--port", "-p", type=int, help="HTTP listen port")
    parser.add_argument("--hermes-url", help="Hermes API base URL")
    parser.add_argument("--hermes-key", help="Hermes API key")
    parser.add_argument("--db-dir", help="Directory for SQLite databases")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--base-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=60.0)
    args = parser.parse_args()

    config = build_config(args)
    broker = ConnectionBroker(config)
    server = MaestroServer(broker, port=config.listen_port)

    # Load plugins from config
    plugins = PluginManager(broker)
    plugins.register(CalendarTriggerPlugin())
    file_config = load_config(args.config) if args.config else {}
    plugin_configs = file_config.get("plugins", {})
    for name, plugin_config in plugin_configs.items():
        await plugins.load(name, plugin_config)

    await broker.start()
    await server.start()

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
        await broker.stop()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
