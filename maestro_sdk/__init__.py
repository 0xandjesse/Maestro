"""Maestro SDK — Python implementation of the Maestro agent messaging protocol.

Provides persistent message queues, contact graph management, blackboards,
and pluggable transport for agent-to-agent communication.
"""
from .transport.broker import ConnectionBroker, TransportConfig
from .transport.server import MaestroServer
from .storage.queue import MessageQueue, QueuedMessage
from .storage.registry import AgentRegistry, ContactCard
from .storage.blackboard import BlackboardStore
from .plugins.manager import Plugin, PluginManager

__version__ = "0.1.0"
__all__ = [
    "ConnectionBroker",
    "TransportConfig",
    "MaestroServer",
    "MessageQueue",
    "QueuedMessage",
    "AgentRegistry",
    "ContactCard",
    "BlackboardStore",
    "Plugin",
    "PluginManager",
]
