"""Persistent message queue with at-least-once delivery."""
import json
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List

@dataclass
class QueuedMessage:
    id: str
    sender_agent_id: str
    recipient_agent_id: str
    msg_type: str
    content: str
    headers: str  # JSON
    status: str  # pending | delivered | failed
    attempts: int
    created_at: float
    updated_at: float
    next_attempt_at: Optional[float]
    last_error: Optional[str]

class MessageQueue:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender_agent_id TEXT NOT NULL,
                    recipient_agent_id TEXT NOT NULL,
                    msg_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    headers TEXT,
                    status TEXT DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    next_attempt_at REAL,
                    last_error TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status_next_attempt
                ON messages(status, next_attempt_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recipient_status
                ON messages(recipient_agent_id, status)
            """)

    def enqueue(self, msg: QueuedMessage) -> bool:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO messages
                    (id, sender_agent_id, recipient_agent_id, msg_type, content, headers,
                     status, attempts, created_at, updated_at, next_attempt_at, last_error)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (msg.id, msg.sender_agent_id, msg.recipient_agent_id,
                     msg.msg_type, msg.content, msg.headers,
                     msg.status, msg.attempts, msg.created_at, msg.updated_at,
                     msg.next_attempt_at, msg.last_error)
                )
            return True
        except Exception:
            return False

    def mark_retry(self, msg_id: str, next_attempt: float) -> bool:
        """Set message back to pending for a retry attempt, incrementing attempts."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "UPDATE messages SET status='pending', updated_at=?, next_attempt_at=?, attempts=attempts+1 WHERE id=?",
                    (time.time(), next_attempt, msg_id)
                )
            return True
        except Exception:
            return False

    def mark_delivered(self, msg_id: str) -> bool:
        """Mark message as delivered."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "UPDATE messages SET status='delivered', updated_at=? WHERE id=?",
                    (time.time(), msg_id)
                )
            return True
        except Exception:
            return False

    def mark_failed(self, msg_id: str, error: str, next_attempt: Optional[float] = None) -> bool:
        """Mark message as failed. If next_attempt is None, it's permanent."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """UPDATE messages
                    SET status='failed', updated_at=?, last_error=?, next_attempt_at=?
                    WHERE id=?""",
                    (time.time(), error, next_attempt, msg_id)
                )
            return True
        except Exception:
            return False

    def prune(self, max_age_days: int = 7) -> int:
        """Remove delivered/failed messages older than max_age_days. Returns count deleted."""
        cutoff = time.time() - (max_age_days * 86400)
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE status IN ('delivered','failed') AND updated_at < ?",
                (cutoff,)
            )
            return cur.rowcount

    def get_pending(self, limit: int = 100) -> List[QueuedMessage]:
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM messages
                WHERE status='pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY created_at ASC LIMIT ?""",
                (now, limit)
            ).fetchall()
        return [self._row_to_msg(r) for r in rows]

    def get_by_id(self, msg_id: str) -> Optional[QueuedMessage]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        return self._row_to_msg(row) if row else None

    def _row_to_msg(self, row: sqlite3.Row) -> QueuedMessage:
        return QueuedMessage(
            id=row["id"],
            sender_agent_id=row["sender_agent_id"],
            recipient_agent_id=row["recipient_agent_id"],
            msg_type=row["msg_type"],
            content=row["content"],
            headers=row["headers"] or "{}",
            status=row["status"],
            attempts=row["attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            next_attempt_at=row["next_attempt_at"],
            last_error=row["last_error"],
        )
