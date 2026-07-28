"""Groups' own export — every receipt tagged with a `group_id` (§7).

The same live-formula summary technique `excel_general.py` uses, with one added
contributing-user column carrying a **name or email, never a raw `user_id`** — an internal
identifier in a spreadsheet a group manager circulates is a leak of something nobody outside
the system needs.

**Access is gated by Groups, not by this provider.** Persistence stamps `group_id` at write
time and stores it faithfully; who may query across a group is Groups' own rule (§4.1 there).
So this provider calls the injected permission check before generating anything and never
trusts a bare `group_id` parameter on its own. Persistence deciding group access itself would
be exactly the boundary violation its own §1 rules out.
"""

from __future__ import annotations

from typing import Protocol

from common.frozen_dict import FrozenDict

from ..contracts import ExportResult
from ..errors import ACCESS_DENIED, ExportError, ProviderUnavailable
from . import common


class GroupAccessCheck(Protocol):
    """Groups API's own permission gate, behind one small interface (§1.3).

    Returns the display label for each contributing user, keyed by `user_id`, or `None` when
    the caller may not export this group. Two answers in one call because the provider needs
    both and asking twice invites the two answers disagreeing.
    """

    async def resolve_group(
        self, group_id: str, requesting_user_id: str
    ) -> dict[str, str] | None: ...


class GroupExportProvider:
    """Implements `ExportProvider`."""

    name = "group_export"
    format = "xlsx"

    def __init__(self, ctx: common.ExportContext, access: GroupAccessCheck | None = None):
        self._ctx = ctx
        self._access = access

    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult:
        group_id = str(params.get("group_id", ""))
        if not group_id:
            return ExportResult(
                ok=False, error_code=ACCESS_DENIED, error_detail="no group_id supplied"
            )
        if self._access is None:
            # Fail closed on an access question. No configured gate means the permission
            # cannot be checked, and an unchecked permission is a denial, never a default
            # allow (`docs/PRINCIPLES.md` §4.2's posture applied to an access check).
            return ExportResult(
                ok=False,
                error_code=ACCESS_DENIED,
                error_detail="no Groups permission check is configured",
            )
        labels = await self._access.resolve_group(group_id, user_id)
        if labels is None:
            return ExportResult(
                ok=False,
                error_code=ACCESS_DENIED,
                error_detail=f"user {user_id} may not export group {group_id}",
            )

        receipts = await common.fetch_receipts(
            self._ctx, user_id, FrozenDict({**dict(params), "group_id": group_id})
        )
        export_id = common.new_export_id()
        try:
            data = common.build_workbook(
                receipts,
                export_id=export_id,
                extra_columns=("contributed_by",),
                extra_values=lambda r: (labels.get(r.user_id, "unknown contributor"),),
            )
            blob = await common.store_artifact(self._ctx, data)
        except (ProviderUnavailable, ExportError) as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))
        generated_at = await common.record_snapshot(self._ctx, export_id, user_id)
        return ExportResult(
            ok=True,
            export_blob_ref=blob,
            format=self.format,
            generated_at=generated_at,
            export_id=export_id,
            extra_artifacts=FrozenDict(
                {"group_id": group_id, "receipt_count": len(receipts)}
            ),
        )


__all__ = ["GroupAccessCheck", "GroupExportProvider"]
