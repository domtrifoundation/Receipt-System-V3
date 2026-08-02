"""The canonical receipt repository — every write goes through Historian (§3, §5).

**A file the deep-dive's own §2 package layout does not name**, added with a reason: the
layout jumps from `db/schema.py` straight to `service.py`, which is specified as a *thin*
gRPC implementation. The row-mapping and write-path logic has to live somewhere that is not
the servicer, and putting it beside the schema it maps to is the smaller of the available
mistakes.

**There is no write method here that does not carry its Historian event.** `save` takes a
`DataChange` and hands both to `HistorianWriter.write_with_history`, so the canonical row and
its audit record share one transaction. A "just write the row" shortcut is not missing from
this module — it is deliberately absent, because its existence is what would let a canonical
write land without its audit record.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from common.frozen_dict import FrozenDict

from ..contracts import BlobRef, Receipt, ReferenceIdentifier, utcnow
from ..errors import ReceiptNotFound
from ..historian.contracts import DataChange, HistorianEvent
from ..historian.writer import HistorianWriter
from .connection import Database


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


def receipt_to_row(receipt: Receipt) -> dict[str, Any]:
    """The row form, which is also the `before`/`after` payload shape Historian records.

    One function producing both means an event's `after` can never disagree with what was
    actually written — they are literally the same dictionary.
    """
    return {
        "receipt_id": receipt.receipt_id,
        "user_id": receipt.user_id,
        "logical_id": receipt.blob.logical_id,
        "group_id": receipt.group_id,
        "vendor_id": receipt.vendor_id,
        "vendor_name": receipt.vendor_name,
        "transaction_date": receipt.transaction_date.isoformat()
        if receipt.transaction_date
        else None,
        "currency": receipt.currency,
        "total_amount": str(receipt.total_amount) if receipt.total_amount is not None else None,
        "vat_amount": str(receipt.vat_amount) if receipt.vat_amount is not None else None,
        "fields_json": json.dumps(dict(receipt.fields), default=str, sort_keys=True),
        "created_at": receipt.created_at.isoformat(),
        "updated_at": receipt.updated_at.isoformat(),
        "schema_version": receipt.schema_version,
    }


def row_to_receipt(
    row: Mapping[str, Any], identifiers: tuple[ReferenceIdentifier, ...] = ()
) -> Receipt:
    return Receipt(
        receipt_id=row["receipt_id"],
        user_id=row["user_id"],
        blob=BlobRef(row["logical_id"]),
        created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
        updated_at=_dt(row["updated_at"]),  # type: ignore[arg-type]
        group_id=row["group_id"],
        vendor_id=row["vendor_id"],
        vendor_name=row["vendor_name"],
        transaction_date=_dt(row["transaction_date"]),
        currency=row["currency"],
        total_amount=_dec(row["total_amount"]),
        vat_amount=_dec(row["vat_amount"]),
        identifiers=identifiers,
        fields=FrozenDict(json.loads(row["fields_json"])),
        schema_version=int(row["schema_version"]),
    )


class ReceiptRepository:
    """Canonical receipt reads and writes. Writes always pair with a Historian event."""

    def __init__(self, db: Database, historian: HistorianWriter | None = None) -> None:
        self._db = db
        self._historian = historian or HistorianWriter(db)

    # ------------------------------------------------------------------ read
    def get_sync(self, conn: sqlite3.Connection, receipt_id: str) -> Receipt | None:
        row = conn.execute(
            "SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if row is None:
            return None
        idents = conn.execute(
            "SELECT kind, value, normalized FROM reference_identifiers WHERE receipt_id = ?"
            " ORDER BY kind, value",
            (receipt_id,),
        ).fetchall()
        return row_to_receipt(
            dict(row),
            tuple(
                ReferenceIdentifier(kind=i["kind"], value=i["value"], normalized=i["normalized"])
                for i in idents
            ),
        )

    async def get(self, receipt_id: str) -> Receipt | None:
        return await self._db.run(lambda conn: self.get_sync(conn, receipt_id))

    async def list_for_user(
        self, user_id: str, *, after_receipt_id: str = "", limit: int = 500
    ) -> tuple[Receipt, ...]:
        """Cursor-shaped rather than offset-shaped, because Archive Sync's own resume
        behaviour needs a stable position, not a page number that shifts under inserts."""

        def _read(conn: sqlite3.Connection) -> tuple[Receipt, ...]:
            rows = conn.execute(
                "SELECT receipt_id FROM receipts WHERE user_id = ? AND receipt_id > ?"
                " ORDER BY receipt_id LIMIT ?",
                (user_id, after_receipt_id, limit),
            ).fetchall()
            return tuple(
                r for r in (self.get_sync(conn, row["receipt_id"]) for row in rows) if r
            )

        return await self._db.run(_read)

    # ----------------------------------------------------------------- write
    async def save(
        self, receipt: Receipt, *, actor: str
    ) -> tuple[Receipt, HistorianEvent]:
        """Insert or update one receipt and its Historian event, atomically.

        `actor` is required, never defaulted: "who changed this" is the whole point of the
        data-change track, and a default would quietly turn every unattributed write into
        the same anonymous entry. Reimport passes `human:<user_id>-via-reimport` here, which
        is what keeps a round-tripped edit distinguishable from a live in-app one.
        """
        stamped = Receipt(**{**receipt.__dict__, "updated_at": utcnow()})
        after = receipt_to_row(stamped)

        def _txn(conn: sqlite3.Connection) -> tuple[Receipt, HistorianEvent]:
            # The before-image is read inside the transaction, under the same write lock the
            # update lands under — read outside it, it could already be stale.
            existing = self.get_sync(conn, stamped.receipt_id)
            before = receipt_to_row(existing) if existing else None
            _upsert(conn, after)
            _replace_identifiers(conn, stamped)
            change = DataChange(
                table_name="receipts",
                row_id=stamped.receipt_id,
                before=FrozenDict(before) if before else None,
                after=FrozenDict(after),
                actor=actor,
            )
            event = self._historian.append_data_change_sync(conn, change)
            return stamped, event

        return await self._db.transaction(_txn)

    async def apply_field_updates(
        self, receipt_id: str, updates: Mapping[str, Any], *, actor: str
    ) -> tuple[Receipt, HistorianEvent]:
        """Apply a resolved field map to an existing receipt.

        This is the single reusable write Reimport's three-way resolution and Reconciliation's
        own backward-carrying sweep both call — one function, two orchestrators, never a
        second implementation for the historical case (`docs/PRINCIPLES.md` §1.9).
        """
        current = await self.get(receipt_id)
        if current is None:
            raise ReceiptNotFound(receipt_id)
        merged = _merge(current, updates)
        return await self.save(merged, actor=actor)


def _merge(receipt: Receipt, updates: Mapping[str, Any]) -> Receipt:
    """First-class columns update in place; anything else lands in `fields`."""
    columns = {
        k: v for k, v in updates.items() if k in Receipt.__dataclass_fields__ and k != "fields"
    }
    extras = {k: v for k, v in updates.items() if k not in Receipt.__dataclass_fields__}
    fields = FrozenDict({**dict(receipt.fields), **extras}) if extras else receipt.fields
    return Receipt(**{**receipt.__dict__, **columns, "fields": fields})


def _upsert(conn: sqlite3.Connection, row: Mapping[str, Any]) -> None:
    conn.execute(
        "INSERT INTO receipts (receipt_id, user_id, logical_id, group_id, vendor_id,"
        " vendor_name, transaction_date, currency, total_amount, vat_amount, fields_json,"
        " created_at, updated_at, schema_version)"
        " VALUES (:receipt_id,:user_id,:logical_id,:group_id,:vendor_id,:vendor_name,"
        " :transaction_date,:currency,:total_amount,:vat_amount,:fields_json,:created_at,"
        " :updated_at,:schema_version)"
        " ON CONFLICT(receipt_id) DO UPDATE SET user_id=excluded.user_id,"
        " logical_id=excluded.logical_id, group_id=excluded.group_id,"
        " vendor_id=excluded.vendor_id, vendor_name=excluded.vendor_name,"
        " transaction_date=excluded.transaction_date, currency=excluded.currency,"
        " total_amount=excluded.total_amount, vat_amount=excluded.vat_amount,"
        " fields_json=excluded.fields_json, updated_at=excluded.updated_at,"
        " schema_version=excluded.schema_version",
        dict(row),
    )


def _replace_identifiers(conn: sqlite3.Connection, receipt: Receipt) -> None:
    conn.execute(
        "DELETE FROM reference_identifiers WHERE receipt_id = ?", (receipt.receipt_id,)
    )
    conn.executemany(
        "INSERT OR REPLACE INTO reference_identifiers (receipt_id, kind, value, normalized)"
        " VALUES (?,?,?,?)",
        [
            (receipt.receipt_id, i.kind, i.value, i.normalized)
            for i in receipt.identifiers
        ],
    )


__all__ = ["ReceiptRepository", "receipt_to_row", "row_to_receipt"]
