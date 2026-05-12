"""Persistent agent registry with contact graphs."""
import json
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List, Dict

@dataclass
class ContactCard:
    agent_id: str
    wallet_address: Optional[str]
    endpoints: str  # JSON list of {"url": str, "ttl": int, "last_seen": float}
    capabilities: str  # JSON list
    trusted_by: str  # JSON list of agent_ids who vouched
    created_at: float
    updated_at: float
    expires_at: Optional[float]

class AgentRegistry:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    agent_id TEXT PRIMARY KEY,
                    wallet_address TEXT,
                    endpoints TEXT NOT NULL,
                    capabilities TEXT,
                    trusted_by TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires
                ON contacts(expires_at)
            """)

    def upsert_contact(self, card: ContactCard) -> bool:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """INSERT INTO contacts
                    (agent_id, wallet_address, endpoints, capabilities, trusted_by,
                     created_at, updated_at, expires_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                    wallet_address=excluded.wallet_address,
                    endpoints=excluded.endpoints,
                    capabilities=excluded.capabilities,
                    trusted_by=excluded.trusted_by,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at""",
                    (card.agent_id, card.wallet_address, card.endpoints,
                     card.capabilities, card.trusted_by,
                     card.created_at, card.updated_at, card.expires_at)
                )
            return True
        except Exception:
            return False

    def get_contact(self, agent_id: str) -> Optional[ContactCard]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM contacts WHERE agent_id=?", (agent_id,)).fetchone()
        return self._row_to_card(row) if row else None

    def list_contacts(self) -> List[ContactCard]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM contacts").fetchall()
        return [self._row_to_card(r) for r in rows]

    def prune_expired(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute("DELETE FROM contacts WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            return cur.rowcount

    def _row_to_card(self, row: sqlite3.Row) -> ContactCard:
        return ContactCard(
            agent_id=row["agent_id"],
            wallet_address=row["wallet_address"],
            endpoints=row["endpoints"],
            capabilities=row["capabilities"] or "[]",
            trusted_by=row["trusted_by"] or "[]",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
        )
