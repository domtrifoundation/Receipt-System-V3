"""Archive Sync — one-way outbound mirroring of a user's archive.

Import types from `.contracts`. The external copy is a convenience mirror and never a second
source of truth.
"""

from .contracts import SyncCursor, SyncJob, SyncResult, SyncState, SyncTarget
from .providers.base import SyncProviderRegistry, SyncTargetProvider
from .sync import ArchiveSync, external_name

__all__ = [
    "ArchiveSync",
    "SyncCursor",
    "SyncJob",
    "SyncProviderRegistry",
    "SyncResult",
    "SyncState",
    "SyncTarget",
    "SyncTargetProvider",
    "external_name",
]
