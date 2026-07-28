"""Field-level diff between a reimported file's contents and current canonical state (§6).

The parent deep-dive's package layout names `diff.py` and `conflict_resolution.py`; the
sub-API's own layout names `parser.py` and `three_way_diff.py`. Both exist here with the
responsibilities split the obvious way: this module answers *what differs*, `three_way_diff`
answers *who changed it and therefore what wins*, and `conflict_resolution` orchestrates the
whole reimport and raises the flag. Keeping "what differs" separate is what lets the diff be
shown to a user in the reimport-diff UI before anything is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldDelta:
    field: str
    canonical_value: Any
    reimported_value: Any


@dataclass(frozen=True)
class RowDiff:
    receipt_id: str
    deltas: tuple[FieldDelta, ...]

    @property
    def is_empty(self) -> bool:
        return not self.deltas


def diff_row(
    canonical: Mapping[str, Any], reimported: Mapping[str, Any], *, receipt_id: str
) -> RowDiff:
    """Every reimported field whose value differs from canonical, in file order.

    Compared as strings when the two sides have different types, because a workbook round
    trip genuinely changes representation — `Decimal("100.00")` comes back as the float
    `100.0` or the string `"100.00"` depending on how the cell was formatted. Treating that
    as a user edit would manufacture conflicts out of nothing, which is a worse failure than
    missing a real change that only differs by formatting.
    """
    deltas = []
    for field_name, reimp in reimported.items():
        canon = canonical.get(field_name)
        if not values_equal(canon, reimp):
            deltas.append(FieldDelta(field=field_name, canonical_value=canon, reimported_value=reimp))
    return RowDiff(receipt_id=receipt_id, deltas=tuple(deltas))


def values_equal(left: Any, right: Any) -> bool:
    """Equality tolerant of the representation shifts an Excel round trip introduces."""
    if left == right:
        return True
    if left is None or right is None:
        return False
    if type(left) is not type(right):
        return _normalize(left) == _normalize(right)
    return False


def _normalize(value: Any) -> str:
    text = str(value).strip()
    try:
        as_float = float(text)
    except (TypeError, ValueError):
        return text
    # `100`, `100.0` and `100.00` are the same number written three ways.
    return f"{as_float:.10g}"


__all__ = ["FieldDelta", "RowDiff", "diff_row", "values_equal"]
