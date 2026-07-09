"""Session Checkpoint — agent session snapshot persistence.

Exports
-------
* ``SessionState`` — canonical checkpoint representation
* ``SessionCheckpoint`` — abstract interface
* ``FileSessionCheckpoint`` — file-backed implementation
* ``validate_state`` — schema validator
"""

from .interface import SessionCheckpoint, SessionState
from .checkpoint import FileSessionCheckpoint
from .schema import validate_state

__all__ = [
    "FileSessionCheckpoint",
    "SessionCheckpoint",
    "SessionState",
    "validate_state",
]
