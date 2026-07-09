"""Gate Engine — in-memory implementation.

Exports
-------
* ``GateType``, ``GateResult``, ``Gate``, ``TokenLifecycle`` — data types
* ``GateEngine`` — abstract interface
* ``InMemoryGateEngine`` — in-memory implementation
* ``validate_token``, ``validate_gate`` — schema validators
"""

from .interface import Gate, GateEngine, GateResult, GateType, TokenLifecycle
from .engine import InMemoryGateEngine
from .schema import validate_gate, validate_token

__all__ = [
    "Gate",
    "GateEngine",
    "GateResult",
    "GateType",
    "InMemoryGateEngine",
    "TokenLifecycle",
    "validate_gate",
    "validate_token",
]
