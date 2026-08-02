"""Blob backup Provider Registry (§4.4). B2 and Storj run in parallel, both enabled.

Concrete targets are imported here so registration is one obvious place, but each SDK is
still only imported lazily inside its own adapter — importing this package costs nothing.
"""

from .b2_target import B2Config, B2Target
from .base import BackupRegistry, BackupTarget, FanOutResult, InMemoryTarget, TargetOutcome
from .storj_target import StorjConfig, StorjTarget

__all__ = [
    "B2Config",
    "B2Target",
    "BackupRegistry",
    "BackupTarget",
    "FanOutResult",
    "InMemoryTarget",
    "StorjConfig",
    "StorjTarget",
    "TargetOutcome",
]
