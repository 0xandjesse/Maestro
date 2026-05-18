"""Persistent blackboard storage."""
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

class BlackboardStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blackboards (
                    board_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (board_id, key)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_board
                ON blackboards(board_id)
            """)

    def write(self, board_id: str, key: str, value: Any, updated_by: str) -> bool:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """INSERT INTO blackboards (board_id, key, value, updated_by, updated_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(board_id, key) DO UPDATE SET
                    value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
                    (board_id, key, json.dumps(value), updated_by, time.time())
                )
            return True
        except Exception:
            return False

    def read(self, board_id: str, key: Optional[str] = None) -> Optional[Any]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if key:
                row = conn.execute(
                    "SELECT value FROM blackboards WHERE board_id=? AND key=?",
                    (board_id, key)
                ).fetchone()
                return json.loads(row["value"]) if row else None
            else:
                rows = conn.execute(
                    "SELECT key, value, updated_by, updated_at FROM blackboards WHERE board_id=?",
                    (board_id,)
                ).fetchall()
                return {r["key"]: {
                    "value": json.loads(r["value"]),
                    "updated_by": r["updated_by"],
                    "updated_at": r["updated_at"]
                } for r in rows}

    def list_keys(self, board_id: str) -> List[str]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT key FROM blackboards WHERE board_id=?", (board_id,)).fetchall()
        return [r[0] for r in rows]

    def list_boards(self) -> List[str]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT DISTINCT board_id FROM blackboards").fetchall()
        return [r[0] for r in rows]

    def delete(self, board_id: str, key: str) -> bool:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("DELETE FROM blackboards WHERE board_id=? AND key=?", (board_id, key))
            return True
        except Exception:
            return False
