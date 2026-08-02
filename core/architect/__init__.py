"""Architect API — the registry of what is allowed to exist.

Kept import-light on purpose. Other packages import `core.architect.contracts` and
nothing else (`docs/PRINCIPLES.md` §1.1), so this module must not pull the registry,
the vendor directory or temporal_learning into memory as a side effect of that import.
"""

from __future__ import annotations

__all__: list[str] = []
