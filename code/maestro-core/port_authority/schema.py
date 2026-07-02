# nucleus/modules/port_authority/schema.py
"""Schema for port map data."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PortMap:
    version: str = "1.0.0"
    last_updated: str = ""
    agents: dict[str, dict[str, int]] = field(default_factory=dict)
    bridge: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PortMap":
        return cls(
            version=data.get("version", "1.0.0"),
            last_updated=data.get("last_updated", ""),
            agents=data.get("agents", {}),
            bridge=data.get("bridge", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "last_updated": self.last_updated,
            "agents": self.agents,
            "bridge": self.bridge,
        }
