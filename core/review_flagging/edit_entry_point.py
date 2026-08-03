"""The deep-link decision for the system's general in-browser edit entry point
(`v3-deepdive-25-review-flagging-api.md` §3, §4).

**Not its own RPC** — `review_flagging.proto` has no `GetEditLink` call, because the
deep-dive describes this as the destination a flag or a Notifications quick-action button
opens, not a service call in its own right. This module is the pure lookup answering
"which field, if any, does resolving this flag type conventionally correct" so a client
can render the deep-link button without either hardcoding its own copy of this table or
Review/Flagging owning the edit *screen* itself (`CLAUDE.md`'s own "does NOT own the
vendor-management UI" boundary, restated here for the edit form specifically).

The actual write, when a resolution supplies one, goes through `lifecycle.py`'s own
`PersistenceWriteGateway` seam directly — this module never writes anything; it only
names the target.
"""

from __future__ import annotations

from .contracts import EditLink, Flag

#: `flag_type` -> the field a resolution for that type conventionally corrects. Not
#: exhaustive and not authoritative — Architect's registry (`contracts.py`'s own docstring)
#: is the source of truth for what flag types exist at all; this table only says which of
#: them has one obvious single-field deep-link target. A flag type absent here has no
#: single-field target, and a client falls back to opening the receipt generally
#: (`EditLink.field=None`, deep-dive §3) rather than this module guessing at one.
FLAG_TYPE_EDIT_FIELD: dict[str, str] = {
    "vat_math_mismatch": "vat_amount",
    "tin_format_malformed": "vendor_tin",
    "implausible_date": "transaction_date",
    "atp_validity": "atp_number",
    "total_amount_mismatch": "total_amount",
}


def build_edit_link(flag: Flag) -> EditLink:
    """The deep-link target for one flag. Pure, no I/O — matches `contracts.EditLink`'s
    own shape exactly, since this is a lookup, never a query."""
    field = FLAG_TYPE_EDIT_FIELD.get(flag.flag_type)
    label = f"Fix {field.replace('_', ' ')}" if field else "Open receipt"
    return EditLink(flag_id=flag.flag_id, receipt_id=flag.receipt_id, field=field, label=label)


__all__ = ["FLAG_TYPE_EDIT_FIELD", "build_edit_link"]
