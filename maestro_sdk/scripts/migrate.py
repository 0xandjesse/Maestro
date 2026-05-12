"""Migration tool: converts legacy Maestro transport state into the new SDK SQLite schema.

Usage:
    python -m maestro_sdk.scripts.migrate \
        --registry ~/.maestro/registry.json \
        --blackboards ~/.maestro/blackboards \
        --db-dir ~/.maestro/sdk
"""
import argparse
import json
import time
from pathlib import Path

from maestro_sdk.storage.queue import MessageQueue
from maestro_sdk.storage.registry import AgentRegistry, ContactCard
from maestro_sdk.storage.blackboard import BlackboardStore


def migrate_registry(registry_path: Path, registry_db: Path):
    print(f"Migrating registry: {registry_path} -> {registry_db}")
    reg = AgentRegistry(str(registry_db))
    data = json.loads(registry_path.read_text())
    for entry in data:
        agent_id = entry.get("agentId")
        if not agent_id:
            continue
        endpoints = entry.get("webhookEndpoint")
        ep_list = [{"url": endpoints, "ttl": None, "last_seen": None}] if endpoints else []
        now = time.time()
        card = ContactCard(
            agent_id=agent_id,
            wallet_address=entry.get("wallet", ""),
            endpoints=json.dumps(ep_list),
            capabilities=json.dumps(entry.get("capabilities", [])),
            trusted_by=json.dumps(entry.get("trusted_by", [])),
            created_at=entry.get("registeredAt", 0) / 1000 or now,
            updated_at=entry.get("lastSeen", 0) / 1000 or now,
            expires_at=None,
        )
        reg.upsert_contact(card)
    new_count = len(reg.list_contacts())
    print(f"  Migrated {new_count} contacts")


def migrate_blackboards(bb_dir: Path, bb_db: Path):
    print(f"Migrating blackboards: {bb_dir} -> {bb_db}")
    store = BlackboardStore(str(bb_db))
    if not bb_dir.exists():
        print("  No blackboard directory found; skipping.")
        return
    for file in bb_dir.glob("*.json"):
        board_id = file.stem
        data = json.loads(file.read_text())
        for key, entry in data.items():
            store.write(board_id, key, entry.get("value"), updated_by=entry.get("updatedBy", "unknown"))
    # Count total keys
    total = 0
    for board_id in store.list_boards():
        total += len(store.list_keys(board_id))
    print(f"  Migrated keys: {total}")


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy Maestro state to SDK")
    parser.add_argument("--registry", default="~/.maestro/registry.json")
    parser.add_argument("--blackboards", default="~/.maestro/blackboards")
    parser.add_argument("--db-dir", default="~/.maestro/sdk")
    args = parser.parse_args()

    registry_path = Path(args.registry).expanduser()
    bb_dir = Path(args.blackboards).expanduser()
    db_dir = Path(args.db_dir).expanduser()
    db_dir.mkdir(parents=True, exist_ok=True)

    migrate_registry(registry_path, db_dir / "registry.db")
    migrate_blackboards(bb_dir, db_dir / "blackboards.db")
    print(f"Migration complete. DB files in {db_dir}")


if __name__ == "__main__":
    main()
