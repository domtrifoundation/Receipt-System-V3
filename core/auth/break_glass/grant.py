"""Time-boxed, reason-tagged staff access to one client's data (deep-dive §6.3).

Break-glass is **not a permission bit on the staff role**. A staff member has no standing
access to any client's data; a grant is a separate, individually-issued, individually-
expiring object naming exactly one staff member, exactly one client, one reason, and one
end time. That difference is the whole mechanism: a permission bit is on until someone
remembers to turn it off, and a grant is off unless someone deliberately turned it on for a
stated reason and a bounded window.

**Expiry is enforced at `check_access()`, never by a sweep.** `purge_or_mark_expired()`
exists for cleanliness and is registered as a Background Workers job, but the security
boundary never depends on it having run recently. A sweep that is late, wedged, or has
never run at all cannot extend anyone's access by a second.

**Auth is the ledger, not the workflow.** Notifications API surfaces a grant to both the
owner and the affected client (dual notification — a break-glass access is never silent,
`docs/PRINCIPLES.md` §4.3); Audit API records it as a privileged action; a staff-facing
screen is where a request is approved. None of that lives here. This module owns the grant
object and its lifetime, and publishes them for those consumers to read.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from ..contracts import BreakGlassGrant, utcnow
from ..errors import BreakGlassExpired
from ..store import AuthDatabase, in_thread

#: Hook for Audit API (file 01 #14). A grant is a privileged, security-relevant action and
#: is recorded as such — distinct from this API's own operational logging. Injected rather
#: than imported so Auth does not take a hard dependency on Audit being up: if the sink is
#: absent the grant still records in this ledger, which is itself durable evidence.
AuditSink = Callable[[str, dict], None]


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_grant(row) -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=row["grant_id"],
        staff_user_id=row["staff_user_id"],
        target_client_user_id=row["target_client_user_id"],
        reason=row["reason"],
        granted_at=_dt(row["granted_at"]),  # type: ignore[arg-type]
        expires_at=_dt(row["expires_at"]),  # type: ignore[arg-type]
        revoked_at=_dt(row["revoked_at"]),
    )


class BreakGlassLedger:
    def __init__(
        self,
        db: AuthDatabase,
        default_duration_minutes: int = 60,
        max_duration_minutes: int = 480,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self._db = db
        self._default_minutes = default_duration_minutes
        self._max_minutes = max_duration_minutes
        self._audit = audit_sink

    # ------------------------------------------------------------- sync core
    def request_grant_sync(
        self,
        staff_user_id: str,
        target_client_user_id: str,
        reason: str,
        duration_minutes: int | None = None,
    ) -> BreakGlassGrant:
        """`reason` is required and non-empty — enforced here, not left to caller discipline.

        Raises `ValueError` for a missing reason or an out-of-range duration. These are
        rejected *requests*, not failed authentications: nothing was granted, so there is no
        access for a caller to accidentally proceed with, and `ValueError` keeps them
        clearly distinct from `errors.AuthFailure` at the transport layer.
        """
        if not reason or not reason.strip():
            raise ValueError("break-glass requires a non-empty reason")
        minutes = self._default_minutes if duration_minutes is None else int(duration_minutes)
        if minutes <= 0 or minutes > self._max_minutes:
            raise ValueError(
                f"break-glass duration must be 1..{self._max_minutes} minutes, got {minutes}"
            )
        now = utcnow()
        grant = BreakGlassGrant(
            grant_id=secrets.token_urlsafe(16),
            staff_user_id=staff_user_id,
            target_client_user_id=target_client_user_id,
            reason=reason.strip(),
            granted_at=now,
            expires_at=now + timedelta(minutes=minutes),
        )
        self._db.write(
            "INSERT INTO break_glass_grants (grant_id, staff_user_id,"
            " target_client_user_id, reason, granted_at, expires_at, revoked_at)"
            " VALUES (?,?,?,?,?,?,NULL)",
            (grant.grant_id, grant.staff_user_id, grant.target_client_user_id,
             grant.reason, grant.granted_at.isoformat(), grant.expires_at.isoformat()),
        )
        self._emit("break_glass_granted", grant)
        return grant

    def check_access_sync(
        self, staff_user_id: str, target_client_user_id: str, now: datetime | None = None
    ) -> bool:
        """`True` only for an active, unexpired, unrevoked grant covering exactly this pair.

        Called by Persistence/Search-Query before staff read access to a client's folder.
        Expiry is evaluated in the SQL predicate against the current time, which is what
        makes "the instant it expires" literal rather than "the next time the sweep runs".
        """
        row = self._db.query_one(
            "SELECT 1 FROM break_glass_grants WHERE staff_user_id = ?"
            " AND target_client_user_id = ? AND revoked_at IS NULL AND expires_at > ?"
            " LIMIT 1",
            (staff_user_id, target_client_user_id, (now or utcnow()).isoformat()),
        )
        return row is not None

    def assert_access_sync(
        self, staff_user_id: str, target_client_user_id: str, now: datetime | None = None
    ) -> None:
        """Raising form, for a caller that wants the failure to stop it rather than branch.

        Both forms exist because both uses are real: a UI asks *whether* access exists, and
        a data read must not continue *unless* it does.
        """
        if not self.check_access_sync(staff_user_id, target_client_user_id, now):
            raise BreakGlassExpired(
                f"no active break-glass grant for staff {staff_user_id} "
                f"over client {target_client_user_id}"
            )

    def get_sync(self, grant_id: str) -> BreakGlassGrant | None:
        row = self._db.query_one(
            "SELECT * FROM break_glass_grants WHERE grant_id = ?", (grant_id,)
        )
        return _row_to_grant(row) if row else None

    def revoke_sync(self, grant_id: str) -> bool:
        """Early revocation, before natural expiry. One committed row update, effective on
        the next `check_access()` — the same instant-revocation property sessions have."""
        revoked = self._db.write(
            "UPDATE break_glass_grants SET revoked_at = ?"
            " WHERE grant_id = ? AND revoked_at IS NULL",
            (utcnow().isoformat(), grant_id),
        ) == 1
        if revoked:
            grant = self.get_sync(grant_id)
            if grant:
                self._emit("break_glass_revoked", grant)
        return revoked

    def list_active_sync(self, now: datetime | None = None) -> list[BreakGlassGrant]:
        rows = self._db.query_all(
            "SELECT * FROM break_glass_grants WHERE revoked_at IS NULL AND expires_at > ?"
            " ORDER BY granted_at DESC",
            ((now or utcnow()).isoformat(),),
        )
        return [_row_to_grant(r) for r in rows]

    def list_for_client_sync(self, target_client_user_id: str) -> list[BreakGlassGrant]:
        """Every grant ever issued over this client's data, active or not.

        The client is entitled to see this whole history, not only what is live right now —
        which is the reason this returns expired and revoked grants too.
        """
        rows = self._db.query_all(
            "SELECT * FROM break_glass_grants WHERE target_client_user_id = ?"
            " ORDER BY granted_at DESC",
            (target_client_user_id,),
        )
        return [_row_to_grant(r) for r in rows]

    def sweep_expired_sync(self, now: datetime | None = None) -> int:
        """Marks visibly-expired grants as revoked so listings stay tidy.

        Returns how many it touched. Nothing above reads this value as a security fact —
        `check_access_sync` would already have returned `False` for every one of them.
        """
        moment = (now or utcnow()).isoformat()
        return self._db.write(
            "UPDATE break_glass_grants SET revoked_at = expires_at"
            " WHERE revoked_at IS NULL AND expires_at <= ?",
            (moment,),
        )

    def _emit(self, event: str, grant: BreakGlassGrant) -> None:
        if self._audit is None:
            return
        self._audit(event, {
            "grant_id": grant.grant_id,
            "staff_user_id": grant.staff_user_id,
            "target_client_user_id": grant.target_client_user_id,
            "reason": grant.reason,
            "granted_at": grant.granted_at.isoformat(),
            "expires_at": grant.expires_at.isoformat(),
        })

    # ---------------------------------------------------------- async surface
    async def request_grant(
        self, staff_user_id: str, target_client_user_id: str, reason: str,
        duration_minutes: int | None = None,
    ) -> BreakGlassGrant:
        return await in_thread(
            self.request_grant_sync, staff_user_id, target_client_user_id, reason,
            duration_minutes,
        )

    async def check_access(self, staff_user_id: str, target_client_user_id: str) -> bool:
        return await in_thread(self.check_access_sync, staff_user_id, target_client_user_id)

    async def revoke(self, grant_id: str) -> bool:
        return await in_thread(self.revoke_sync, grant_id)

    async def list_active(self) -> list[BreakGlassGrant]:
        return await in_thread(self.list_active_sync)


__all__ = ["AuditSink", "BreakGlassLedger"]
