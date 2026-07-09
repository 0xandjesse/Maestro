"""Bridge Surface — platform-routing surface with visibility gating.

Exports
-------
* ``SurfaceMessage`` — message to be surfaced
* ``SurfaceResult`` — result of a surface operation
* ``BridgeSurface`` — abstract interface
* ``BridgeSurfaceImpl`` — concrete implementation with platform stubs
* ``validate_surface_message`` — schema validator
"""

from .interface import BridgeSurface, SurfaceMessage, SurfaceResult
from .bridge import BridgeSurfaceImpl
from .schema import validate_surface_message

__all__ = [
    "BridgeSurface",
    "BridgeSurfaceImpl",
    "SurfaceMessage",
    "SurfaceResult",
    "validate_surface_message",
]
