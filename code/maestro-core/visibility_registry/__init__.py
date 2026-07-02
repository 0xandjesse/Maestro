"""Visibility Registry — per-agent display-mode configuration.

Exports
-------
* ``VisibilityConfig`` — canonical visibility configuration
* ``VisibilityRegistry`` — abstract interface
* ``FileVisibilityRegistry`` — file-backed implementation
* ``validate_config``, ``validate_registry`` — schema validators
"""

from .interface import VisibilityConfig, VisibilityRegistry
from .registry import FileVisibilityRegistry
from .schema import validate_config, validate_registry

__all__ = [
    "FileVisibilityRegistry",
    "VisibilityConfig",
    "VisibilityRegistry",
    "validate_config",
    "validate_registry",
]
