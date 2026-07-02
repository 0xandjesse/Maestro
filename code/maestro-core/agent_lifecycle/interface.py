"""Agent Lifecycle — Interface Contract.

Defines AgentSpec, AgentCreateResult, and the AgentLifecycle
abstract base class that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentSpec:
    """Specification for creating a new agent."""

    agent_id: str
    display_name: str
    role: str
    model: str
    provider: str
    transport_port: int | None = None   # auto-assigned if None
    gateway_port: int | None = None


@dataclass
class AgentCreateResult:
    """Result of a successful agent creation."""

    agent_id: str
    config_path: str
    transport_port: int
    gateway_port: int
    systemd_unit: str
    warnings: list[str] = field(default_factory=list)


class AgentLifecycle(ABC):
    """Abstract interface for agent lifecycle management.

    Implementations must provide create, destroy, list, health_check,
    and restart operations.  The default in-memory implementation
    delegates port assignment, config generation, and registration
    to the respective modules.
    """

    @abstractmethod
    def create(self, spec: AgentSpec) -> AgentCreateResult:
        """Full agent creation pipeline.

        1. Assign ports from Port Authority (if not specified)
        2. Generate config from Config Generator
        3. Register in Registry Manager
        4. Generate systemd unit name
        5. Return AgentCreateResult
        """
        ...

    @abstractmethod
    def destroy(self, agent_id: str) -> bool:
        """Remove agent from registry, delete config, release ports.

        Returns True if the agent existed.
        """
        ...

    @abstractmethod
    def list_agents(self) -> list[AgentSpec]:
        """Return all registered agents as AgentSpec list."""
        ...

    @abstractmethod
    def health_check(self, agent_id: str) -> tuple[bool, str]:
        """Check if agent is registered and recently seen.

        Returns (healthy, detail).
        """
        ...

    @abstractmethod
    def restart(self, agent_id: str) -> bool:
        """Mark agent for restart.  Returns True if agent exists."""
        ...
