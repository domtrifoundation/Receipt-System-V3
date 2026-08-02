"""Reconciliation API — correction propagation and the validation check inventory.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1).

Reconciliation owns two things (§1): pushing an Architect registry correction out to every
receipt already written that referenced the changed entity, and running §4's check inventory
over receipts to surface Review/Flagging flags. It does not own the flag taxonomy (Architect
does), does not own the learning mechanism that produced the correction (Architect's
`temporal_learning`), and does not run as a competing scheduler (Background Workers owns
dispatch).

The governing rule for this package is `docs/PRINCIPLES.md` §1.9: anything the live pipeline can
do, Reconciliation does to old data through the identical function, never a second
implementation for the historical case. Two checks make that concrete and are tested for object
identity rather than for agreement — §4.11's geo cross-reference and §4.10's archive-reference
check — as does §8's propagation atomicity, which reuses Execution Core's own checkpoint
mechanism rather than reimplementing "resume after a crash".
"""

from __future__ import annotations

__all__: list[str] = []
