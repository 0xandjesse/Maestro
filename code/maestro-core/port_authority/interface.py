# nucleus/modules/port_authority/interface.py
from dataclasses import dataclass


@dataclass
class PortAssignment:
    agent_id: str
    transport_port: int
    gateway_port: int


class PortAuthority:
    """Abstract interface for port assignment and verification."""

    def resolve(self, agent_id: str) -> PortAssignment:
        raise NotImplementedError

    def assign(self, agent_id: str, transport_port: int, gateway_port: int) -> PortAssignment:
        raise NotImplementedError

    def verify(self) -> tuple[bool, list[str]]:
        raise NotImplementedError

    def list_all(self) -> list[PortAssignment]:
        raise NotImplementedError

    def is_port_available(self, port: int) -> bool:
        raise NotImplementedError
