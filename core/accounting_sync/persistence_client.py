"""A thin gRPC client fetching a single `Receipt` from Persistence API by id.

`sync_engine.py`'s `push_receipt()` needs the real receipt a `receipt_id` names, not just
the id itself — `mapping.py` duck-types against `core.persistence.contracts.Receipt`'s
own attribute shape (deep-dive §1's own "never invents its own vendor identity" boundary,
which starts from reading Persistence's own canonical record). This client fetches
`ReceiptMessage` over gRPC and builds a plain, local `_ReceiptView` satisfying the exact
attribute set `mapping.py` reads (`vendor_name`, `total_amount`, `transaction_date`,
`currency`, `fields`), rather than importing `core.persistence.contracts.Receipt`
directly — the same duck-typed cross-API boundary choice `mapping.py`'s own docstring
already makes, extended one level further to the fetch itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

__all__ = ["PersistenceClient", "ReceiptNotFound"]

DEFAULT_PERSISTENCE_ADDRESS = "127.0.0.1:50072"


class ReceiptNotFound(Exception):
    """No receipt with the given id exists for this user, or Persistence is unreachable."""


@dataclass(frozen=True)
class _ReceiptView:
    receipt_id: str
    vendor_name: str
    total_amount: Decimal | None
    transaction_date: datetime | None
    currency: str
    fields: dict = field(default_factory=dict)


class PersistenceClient:
    def __init__(self, address: str = DEFAULT_PERSISTENCE_ADDRESS, timeout_seconds: float = 5.0) -> None:
        self._address = address
        self._timeout_seconds = timeout_seconds

    async def get_receipt(self, user_id: str, receipt_id: str) -> _ReceiptView:
        try:
            import grpc

            from core.persistence.generated import persistence_pb2 as pb
            from core.persistence.generated import persistence_pb2_grpc as pb_grpc
        except ImportError as exc:
            raise ReceiptNotFound(f"persistence client unavailable: {exc}") from exc

        try:
            async with grpc.aio.insecure_channel(self._address) as channel:
                stub = pb_grpc.PersistenceServiceStub(channel)
                response = await stub.GetReceipt(
                    pb.GetReceiptRequest(user_id=user_id, receipt_id=receipt_id),
                    timeout=self._timeout_seconds,
                )
        except Exception as exc:  # noqa: BLE001 - unreachable/timeout is the same "can't get the receipt" outcome
            raise ReceiptNotFound(f"persistence service unreachable: {exc}") from exc

        if response.error_code:
            raise ReceiptNotFound(response.error_detail or response.error_code)

        msg = response.receipt
        total = Decimal(msg.total_amount) if msg.total_amount else None
        txn_date = datetime.fromisoformat(msg.transaction_date) if msg.transaction_date else None
        fields = json.loads(msg.fields_json) if msg.fields_json else {}

        return _ReceiptView(
            receipt_id=msg.receipt_id,
            vendor_name=msg.vendor_name,
            total_amount=total,
            transaction_date=txn_date,
            currency=msg.currency,
            fields=fields,
        )
