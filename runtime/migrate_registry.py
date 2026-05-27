#!/usr/bin/env python3
"""Migrate ~/.maestro/registry.json into the Master Vault.

One-shot migration script. Reads registry.json, imports each agent's
endpoint/port info into the vault's port_registry, and creates a
backup of registry.json before completing.

Can also be called programmatically from vault_cli.py import-registry.

Usage:
    python migrate_registry.py [--registry PATH] [--vault-path PATH] [--key-path PATH]
"""

import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vault import (
    MasterVault,
    VaultError,
    VaultNotFoundError,
    VAULT_DEFAULT_PATH,
    KEY_DEFAULT_PATH,
)

log = logging.getLogger(__name__)

REGISTRY_DEFAULT_PATH = os.path.expanduser("~/.maestro/registry.json")


def _extract_port_from_endpoint(endpoint: str) -> Optional[int]:
    """Extract port number from an HTTP endpoint URL.

    e.g. 'http://127.0.0.1:3843/message' -> 3843
    """
    try:
        # Simple parse — host:port/path
        if ":" not in endpoint:
            return None
        # Get the part after last colon before any slash
        host_port_path = endpoint.split("//", 1)[-1]  # strip scheme
        port_part = host_port_path.split(":", 1)[-1]  # after host
        port_str = port_part.split("/")[0]  # before path
        return int(port_str)
    except (ValueError, IndexError):
        return None


def import_registry(vault: MasterVault, registry_path: str) -> int:
    """Import registry.json entries into the vault.

    For each agent in registry.json, adds a port_registry entry
    with the transport port extracted from the webhookEndpoint.

    Returns the number of agents imported.
    """
    registry_file = Path(registry_path)
    if not registry_file.exists():
        raise FileNotFoundError(f"Registry not found at {registry_path}")

    try:
        entries = json.loads(registry_file.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in registry: {e}")

    if not isinstance(entries, list):
        raise ValueError(f"Expected list in registry, got {type(entries).__name__}")

    # Try to load vault; init if it doesn't exist
    try:
        data = vault._load()
    except VaultNotFoundError:
        # Need to init vault first
        if not vault.key_path.exists():
            vault.init_key()
        vault.init_vault()
        data = vault._load()

    imported = 0
    assignments = data["port_registry"]["assignments"]
    transport_base = data["port_registry"]["transport_base"]

    for entry in entries:
        agent_id = entry.get("agentId")
        endpoint = entry.get("webhookEndpoint", "")

        if not agent_id:
            log.warning("Skipping registry entry with no agentId: %s", entry)
            continue

        # Skip if already in vault
        if agent_id in assignments:
            log.info("Agent '%s' already in vault, skipping", agent_id)
            continue

        # Extract transport port from endpoint
        transport_port = _extract_port_from_endpoint(endpoint)

        # Derive gateway port (gateway = transport_base + offset, but we follow
        # the pattern: transport ports are in 3840+ range, gateways in 8640+ range)
        # The gateway port pattern: gateway_base + same offset as transport
        if transport_port is not None:
            offset = transport_port - transport_base
            gateway_port = data["port_registry"]["gateway_base"] + offset
        else:
            # Fallback: allocate next free
            gateway_port = None

        if gateway_port is not None and transport_port is not None:
            assignments[agent_id] = {
                "gateway": gateway_port,
                "transport": transport_port,
            }
            imported += 1
            log.info("Imported '%s': gateway=%d transport=%d from endpoint=%s",
                     agent_id, gateway_port, transport_port, endpoint)
        else:
            log.warning("Could not extract ports for '%s' from endpoint '%s'",
                        agent_id, endpoint)

    if imported > 0:
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        vault._save(data)

        # Backup registry.json
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = registry_file.parent / f"registry.json.bak-{ts}"
        shutil.copy2(registry_file, backup_path)
        log.info("Registry backed up to %s", backup_path)

    return imported


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate registry.json into Master Vault")
    parser.add_argument("--registry-path", default=REGISTRY_DEFAULT_PATH,
                        help="Path to registry.json")
    parser.add_argument("--vault-path", default=VAULT_DEFAULT_PATH,
                        help="Path to vault.json")
    parser.add_argument("--key-path", default=KEY_DEFAULT_PATH,
                        help="Path to .vault_key")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] [migrate] %(message)s",
                        datefmt="%H:%M:%S")

    vault = MasterVault(vault_path=args.vault_path, key_path=args.key_path)

    try:
        count = import_registry(vault, args.registry_path)
        print(f"Imported {count} agent(s) from registry into vault.")

        if count > 0:
            print("Registry has been backed up. You can safely remove registry.json "
                  "once you've verified the vault contents.")
    except Exception as e:
        print(f"Migration failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()