"""Swappable Core-API transports for Agent Control (`docs/PRINCIPLES.md` §1.3)."""

from .base import CoreBackend
from .local import LocalCoreBackend

__all__ = ["CoreBackend", "LocalCoreBackend"]
