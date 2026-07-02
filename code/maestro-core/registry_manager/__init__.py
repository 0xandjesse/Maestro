"""Registry Manager — single-writer-safe agent registry.

Exports
-------
* ``AgentRecord`` — canonical agent representation
* ``RegistryManager`` — abstract interface
* ``FileRegistryManager`` — file-backed implementation
* ``validate_record``, ``validate_registry`` — schema validators
"""

from .interface import AgentRecord, RegistryManager
from .manager import FileRegistryManager
from .schema import validate_record, validate_registry

__all__ = [
    "AgentRecord",
    "FileRegistryManager",
    "RegistryManager",
    "validate_record",
    "validate_registry",
]
