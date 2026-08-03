"""`IngestionSource` — the Protocol every source Provider Registry entry implements
(deep-dive §1-§4). Every source is independently enableable; a self-hosted install with no
Drive configured degrades to direct-upload-only cleanly, never errors
(`docs/PRINCIPLES.md` §4.4).

**Only `source`/`is_available` are shared across every source.** Beyond that, each
source's actual acquisition shape genuinely differs — direct upload *receives* bytes
Gateway already has in hand, Drive *polls or gets pushed to* and then *downloads by file
ID*, the scanner runs an entirely session-based multi-frame capture flow. Forcing all
three into one identical `list_new_files()`/`download()` shape (as an earlier sketch
implied) would mean direct upload implementing two methods it structurally cannot use
meaningfully — the same reasoning OCR's own engine Protocol keeps deliberately minimal
(`core/ocr/engines/base.py`) rather than over-specifying a shape only some providers need.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts import SourceKind

__all__ = ["IngestionSource"]


@runtime_checkable
class IngestionSource(Protocol):
    @property
    def source(self) -> SourceKind: ...

    async def is_available(self) -> bool: ...
