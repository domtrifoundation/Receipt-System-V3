"""The workbook representation ↔ canonical row image translation (§3, §4).

**Why this module exists, stated as the bug it fixes.** Reimport's three-way diff compares
three things that must be in *one* representation to be comparable at all:

- `original` — the baseline, reconstructed from Historian's append-only trail, which stores
  the canonical row image (`db/receipts.receipt_to_row`): `transaction_date` as a full
  timezone-aware ISO datetime, amounts as `str(Decimal)`, an absent `group_id` as `None`.
- `canonical` — the same row image, read now.
- `reimported` — cells read out of the user's workbook, which
  `exports/providers/common.receipt_row` wrote in a deliberately *lossier*, human-facing
  form: `transaction_date` as a date-only string, `None` rendered as `""`.

Diffing those two representations directly reports "the user changed this" for every single
receipt that has a transaction date, because `"2026-07-17"` never equals
`"2026-07-17T09:30:00+00:00"`. Two consequences, both real: a pure round trip with no user
edit at all wrote every row back and filled the Historian trail with phantom changes, and
the date-only *string* was assigned straight into `Receipt.transaction_date`, so the next
`receipt_to_row` call raised `AttributeError: 'str' object has no attribute 'isoformat'`
out through `ReimportService.submit` — an exception across what will be a gRPC boundary,
which `docs/PRINCIPLES.md` §4.1 rules out on its own.

**The fix, in two halves.** `project_row` puts the canonical and baseline images into the
workbook's own representation before they are compared, so "did the user change this" is
asked about values that were ever comparable. `coerce_updates` converts an applied cell back
into the field's real type before it is written, so a `str` can never reach a `datetime`
column. Neither half guesses: a cell that cannot be converted is *reported*, never dropped
silently and never written as-is (§4.3).

The date-only round trip is genuinely lossy — the export only ever offered the user a date,
so a date the user really did edit comes back at midnight UTC. That loss is the export
format's, not this module's, and it now only happens when the user actually edited the cell.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from common.frozen_dict import FrozenDict


class ValueNotCoercible(ValueError):
    """A workbook cell that cannot be turned into the field's real type.

    Raised only inside this module and caught by `coerce_updates`, which reports the field
    rather than letting it escape — an unparseable edit is surfaced, never silently ignored.
    """


# ------------------------------------------------------------------ projection
def _project_date(value: Any) -> str:
    """Canonical `transaction_date` → the date-only string the workbook carries."""
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return str(value)


def _project_text(value: Any) -> str:
    """`None` renders as `""` in a spreadsheet cell — that is not the user clearing it."""
    return "" if value is None else str(value)


#: Column → how a canonical row image's value is rendered into the workbook. A module-level
#: constant lookup table, therefore a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1).
PROJECTIONS = FrozenDict(
    {
        "transaction_date": _project_date,
        "vendor_name": _project_text,
        "currency": _project_text,
        "total_amount": _project_text,
        "vat_amount": _project_text,
        "group_id": _project_text,
    }
)


# ------------------------------------------------------------------- coercion
def _coerce_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueNotCoercible(f"'{value}' is not a date") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _coerce_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueNotCoercible(f"'{value}' is not an amount") from exc


def _coerce_optional_text(value: Any) -> str | None:
    text = "" if value is None else str(value)
    return text or None


def _coerce_text(value: Any) -> str:
    return "" if value is None else str(value)


#: Column → how a workbook cell becomes the canonical field's real type. Constant, so
#: `FrozenDict` (§2.1.1). A column absent from this table is a free-form extra that lands in
#: `Receipt.fields` untouched, which is the correct behaviour for a column Architect owns the
#: meaning of rather than this module.
COERCIONS = FrozenDict(
    {
        "transaction_date": _coerce_datetime,
        "vendor_name": _coerce_text,
        "currency": _coerce_text,
        "total_amount": _coerce_decimal,
        "vat_amount": _coerce_decimal,
        "group_id": _coerce_optional_text,
    }
)


def project_row(row: Mapping[str, Any]) -> FrozenDict:
    """Render a canonical row image into the workbook's own representation.

    Typed and checked as `Mapping`, never `dict`: these arrive as `FrozenDict` and the 3.15
    builtin is not a `dict` subclass (`docs/PRINCIPLES.md` §2.1).
    """
    if not isinstance(row, Mapping):
        raise TypeError(f"row must be a Mapping, got {type(row)!r}")
    return FrozenDict(
        {
            key: PROJECTIONS[key](value) if key in PROJECTIONS else value
            for key, value in row.items()
        }
    )


def coerce_updates(
    updates: Mapping[str, Any],
) -> tuple[FrozenDict, tuple[str, ...]]:
    """Convert applied workbook cells back into canonical field types.

    Returns the writable updates plus the names of any fields whose value could not be
    converted. A rejected field is *reported*, never applied as-is and never quietly
    dropped — writing a `str` into a `datetime` column is what produced the crash this
    module exists to prevent, and silently discarding a user's edit is the other half of the
    same failure.
    """
    if not isinstance(updates, Mapping):
        raise TypeError(f"updates must be a Mapping, got {type(updates)!r}")
    writable: dict[str, Any] = {}
    rejected: list[str] = []
    for name, value in updates.items():
        coerce = COERCIONS.get(name)
        if coerce is None:
            writable[name] = value
            continue
        try:
            writable[name] = coerce(value)
        except ValueNotCoercible:
            rejected.append(name)
    return FrozenDict(writable), tuple(rejected)


__all__ = [
    "COERCIONS",
    "PROJECTIONS",
    "ValueNotCoercible",
    "coerce_updates",
    "project_row",
]
