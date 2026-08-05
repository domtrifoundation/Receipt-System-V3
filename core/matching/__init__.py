"""Matching API — fuzzy vendor/franchiser matching against Architect's Vendor Directory.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1), and re-exporting `match_vendor` here would
quietly make `from core.matching import match_vendor` look like the supported entry point
when the supported entry point is the gRPC service in `service.py`.

Matching consumes Architect's Vendor Directory; it never holds a copy of it and never learns
from a match itself (`v3-deepdive-15-matching-api.md` §1). Nothing in this package decides what
happens with a low-confidence match beyond the resolved §5 corroboration-context gate — that is
as far as this API's own boundary goes.
"""

from __future__ import annotations

__all__: list[str] = []
