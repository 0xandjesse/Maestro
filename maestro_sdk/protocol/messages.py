"""Maestro protocol message schemas and validation."""
import json
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from datetime import datetime

@dataclass
class MaestroMessage:
    id: str
    type: str
    sender: Dict[str, str]
    content: str
    recipient: Optional[str] = None
    timestamp: Optional[int] = None
    version: str = "3.2"
    stage_id: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "type": self.type,
            "sender": self.sender,
            "content": self.content,
        }
        if self.recipient:
            d["recipient"] = self.recipient
        if self.timestamp:
            d["timestamp"] = self.timestamp
        if self.stage_id:
            d["stageId"] = self.stage_id
        if self.headers:
            d["headers"] = self.headers
        d["version"] = self.version
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaestroMessage":
        return cls(
            id=data["id"],
            type=data["type"],
            sender=data["sender"],
            content=data["content"],
            recipient=data.get("recipient"),
            timestamp=data.get("timestamp"),
            version=data.get("version", "3.2"),
            stage_id=data.get("stageId"),
            headers=data.get("headers"),
        )

@dataclass
class ContactCard:
    """Agent identity card for decentralized discovery."""
    agent_id: str
    wallet_address: Optional[str] = None
    endpoints: Optional[list] = None  # [{"url": str, "ttl": int, "last_seen": float}]
    capabilities: Optional[list] = None
    trusted_by: Optional[list] = None  # agent_ids who vouched
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    expires_at: Optional[float] = None  # TTL in epoch seconds

    def to_dict(self) -> Dict[str, Any]:
        d = {"agentId": self.agent_id}
        if self.wallet_address:
            d["walletAddress"] = self.wallet_address
        if self.endpoints:
            d["endpoints"] = self.endpoints
        if self.capabilities:
            d["capabilities"] = self.capabilities
        if self.trusted_by:
            d["trustedBy"] = self.trusted_by
        if self.created_at:
            d["createdAt"] = int(self.created_at * 1000)
        if self.updated_at:
            d["updatedAt"] = int(self.updated_at * 1000)
        if self.expires_at:
            d["expiresAt"] = int(self.expires_at * 1000)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactCard":
        return cls(
            agent_id=data["agentId"],
            wallet_address=data.get("walletAddress"),
            endpoints=data.get("endpoints", []),
            capabilities=data.get("capabilities", []),
            trusted_by=data.get("trustedBy", []),
            created_at=data.get("createdAt", 0) / 1000 if data.get("createdAt") else None,
            updated_at=data.get("updatedAt", 0) / 1000 if data.get("updatedAt") else None,
            expires_at=data.get("expiresAt", 0) / 1000 if data.get("expiresAt") else None,
        )
