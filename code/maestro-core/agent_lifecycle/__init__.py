"""Agent Lifecycle — full agent creation and management.

Exports
-------
* ``AgentSpec`` — specification for creating a new agent
* ``AgentCreateResult`` — result of a successful agent creation
* ``AgentLifecycle`` — abstract interface
* ``InMemoryAgentLifecycle`` — in-memory implementation
* ``validate_agent_spec`` — schema validator for agent specs
* ``validate_create_result`` — schema validator for create results
"""

from .interface import AgentCreateResult, AgentLifecycle, AgentSpec
from .lifecycle import InMemoryAgentLifecycle
from .schema import validate_agent_spec, validate_create_result

__all__ = [
    "AgentCreateResult",
    "AgentLifecycle",
    "AgentSpec",
    "InMemoryAgentLifecycle",
    "validate_agent_spec",
    "validate_create_result",
]
