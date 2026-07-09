# nucleus/modules/config_generator/interface.py
"""Config Generator — Interface Contract.

Defines AgentConfig, ConfigTemplate, and the ConfigGenerator
abstract base class that all implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """A complete agent configuration record."""

    agentId: str
    port: int
    hermesApiUrl: str
    hermesApiKey: str
    conversation: str
    registryPath: str
    version: str
    knownPeers: dict[str, str]
    surfaceToGateway: bool
    gatewayBridgeUrl: str
    dm_policy: dict | None = None
    registry_signer_public_key: str | None = None


@dataclass
class ConfigTemplate:
    """Base template with defaults. Overrides are agent-specific."""

    version: str = "3.2"
    hermesApiKey: str = "maestro-local-dev"
    registryPath: str = "~/.maestro/registry.json"
    surfaceToGateway: bool = True
    gatewayBridgeUrl: str = "http://127.0.0.1:8653/maestro/notify"  # event bus


class ConfigGenerator(ABC):
    """Abstract interface for config generation, validation, and persistence."""

    @abstractmethod
    def generate(
        self, agent_id: str, overrides: dict | None = None
    ) -> AgentConfig:
        """Create an AgentConfig from template + overrides.

        Auto-assigns port from Port Authority.
        Auto-populates knownPeers from the registry.

        Parameters
        ----------
        agent_id : str
            The agent to generate a config for.
        overrides : dict | None
            Optional field overrides to apply on top of template defaults.

        Returns
        -------
        AgentConfig
            The generated configuration.
        """
        ...

    @abstractmethod
    def validate(self, config: AgentConfig) -> list[str]:
        """Validate *config* and return a list of issues (empty = valid).

        Parameters
        ----------
        config : AgentConfig
            The configuration to validate.

        Returns
        -------
        list[str]
            Human-readable issue descriptions. Empty list means valid.
        """
        ...

    @abstractmethod
    def write(self, agent_id: str, config: AgentConfig) -> str:
        """Persist *config* to disk and return the file path.

        Writes to ``nucleus/data/configs/{agent_id}.json`` using an
        atomic write (temp file + rename).

        Parameters
        ----------
        agent_id : str
            The agent identifier (used for the filename).
        config : AgentConfig
            The configuration to persist.

        Returns
        -------
        str
            Absolute path to the written config file.
        """
        ...

    @abstractmethod
    def regenerate_all(self) -> dict[str, AgentConfig]:
        """Regenerate configs for all known agents.

        Returns
        -------
        dict[str, AgentConfig]
            Mapping of agent_id → AgentConfig for every registered agent.
        """
        ...
