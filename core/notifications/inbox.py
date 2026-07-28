"""The in-app inbox — the one channel that is fully durable today (§3), and its read gate.

**Two postures sit side by side here, deliberately** (matching `core/logs/query.py`'s own
split):

- The **identity/cross-user gate fails closed** (`docs/PRINCIPLES.md` §4.2). No checker wired
  up, an unresolvable session, a checker that cannot be reached — all denied. A client's inbox
  can carry real receipt-adjacent content (a break-glass reason, a run's own summary), so a
  cross-user read follows the identical fail-closed posture Logs and Audit already apply to
  comparable per-user data.
- **Category acceptance degrades gracefully** (§4.4). `CategoryValidator` is not a security
  check — an unrecognised category is a labeling gap, not a reason to lose the notification —
  so the default validator accepts anything non-empty rather than rejecting.

One `InboxStore` instance serves every user; each user's own row lives in its own sqlite file
(`db.py`), so this module keeps one open connection per user id it has actually touched, closed
together on `close()`. That per-user connection map is genuinely mutable internal state
populated on demand, so it is a plain `dict`, never a `FrozenDict` — `docs/PRINCIPLES.md`
§2.1.1 draws that distinction at intent, and a demand-populated cache is squarely on the
mutable side of it.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from .contracts import (
    CategoryValidator,
    CrossUserAccessChecker,
    InboxQuery,
    InboxQueryResult,
    MarkReadResult,
    Notification,
    NotifyRequest,
    utcnow,
)
from .db import (
    INSERT_NOTIFICATION_SQL,
    connect,
    default_db_path,
    row_to_notification,
    to_storage_ts,
)
from .errors import (
    AccessCheckUnavailable,
    CrossUserAccessDenied,
    InvalidNotification,
    InvalidQuery,
    NotificationNotFound,
    StoreUnavailable,
    code_for,
)
from .metrics import NotificationsMetricsCollector


def new_notification_id() -> str:
    """A UUID4, not a sequence number — mirrors `core/audit/writer.py::new_event_id`'s own
    reasoning: a caller needs a stable id before the row is committed, so a failed write still
    has something to report, and the id must not be guessable well enough to let one user probe
    for another's notification ids."""
    return f"ntf_{uuid.uuid4().hex}"


class PermissiveCategoryValidator:
    """The default `CategoryValidator` (see `contracts.py`'s own docstring on why `category`
    stays a plain string): accepts any non-empty category. Not a security check, so an
    unwired/unreachable Architect registry degrades to "accept it" rather than to "reject
    it" — the opposite posture from the identity gate below, and deliberately so (§4.4)."""

    def is_known(self, category: str) -> bool:
        return bool(category and category.strip())


class DenyCrossUser:
    """The fail-closed default when no real checker is wired up (`docs/PRINCIPLES.md` §4.2) —
    identical in shape and intent to `core/logs/query.py::DenyCrossUser`. Own-user reads still
    work; every cross-user read is denied, which is correct behaviour for a process running
    before Auth is reachable, not a degraded one."""

    def allow_cross_user(self, requesting_user_id, subject_user_id) -> bool:
        return False


class AuthBreakGlassChecker:
    """Adapts Auth's own break-glass grant check without importing Auth
    (`docs/PRINCIPLES.md` §1.3) — the identical adapter shape as
    `core/logs/query.py::AuthBreakGlassChecker`. `check` is injected by whatever holds the
    real Auth gRPC client; when Auth's client exists, this is the one file that changes."""

    def __init__(self, check) -> None:
        self._check = check

    def allow_cross_user(self, requesting_user_id, subject_user_id) -> bool:
        try:
            return bool(self._check(requesting_user_id, subject_user_id))
        except Exception as exc:  # noqa: BLE001 - any failure here is "cannot tell" == denial
            raise AccessCheckUnavailable(str(exc)) from exc


class InboxStore:
    """Serves every RPC this API's inbox surface needs: create, query, mark-read.

    Construct with no arguments for the real per-user databases under `RESIBO_TOP_LEVEL`, or
    pass `top_level` in tests. Pass `checker=` to wire real break-glass evaluation; the default
    denies every cross-user read (fail closed).
    """

    def __init__(
        self,
        top_level: Path | str | None = None,
        *,
        checker: CrossUserAccessChecker | None = None,
        category_validator: CategoryValidator | None = None,
        metrics: NotificationsMetricsCollector | None = None,
    ) -> None:
        self._top_level = top_level
        self._checker: CrossUserAccessChecker = checker or DenyCrossUser()
        self._category_validator: CategoryValidator = (
            category_validator or PermissiveCategoryValidator()
        )
        self._metrics = metrics or NotificationsMetricsCollector()
        self._lock = threading.Lock()
        self._connections: dict[str, object] = {}  # per-user cache, genuinely mutable

    @property
    def metrics(self) -> NotificationsMetricsCollector:
        return self._metrics

    def _conn_for(self, user_id: str):
        with self._lock:
            conn = self._connections.get(user_id)
            if conn is None:
                path = default_db_path(user_id, top_level=self._top_level)
                try:
                    conn = connect(path)
                except OSError as exc:
                    raise StoreUnavailable(f"{path}: {exc}") from exc
                self._connections[user_id] = conn
            return conn

    # ------------------------------------------------------------------ the gate
    def authorize(self, requester: str | None, subject: str) -> None:
        """Raise if this caller may not read/act on `subject`'s inbox. Fails closed —
        identical structure to `core/logs/query.py::LogReader.authorize`."""
        if requester is not None and requester == subject:
            return
        if requester is None:
            raise CrossUserAccessDenied(
                "an unresolvable caller may not read an inbox; inboxes carry per-user content"
            )
        if not self._checker.allow_cross_user(requester, subject):
            raise CrossUserAccessDenied(
                f"{requester!r} has no active break-glass grant for {subject!r}"
            )

    # ------------------------------------------------------------------ write
    def create(self, request: NotifyRequest) -> Notification:
        """Write the in-app record. Always attempted regardless of any outbound channel's own
        outcome — `dispatch.py` calls this first and unconditionally (deep-dive §8's own
        resolved delivery-failure handling: the in-app record is the reliable source of
        truth this API establishes, so it must never depend on an outbound send succeeding).

        Raises `InvalidNotification`/`StoreUnavailable` internally; callers at a gRPC boundary
        turn that into `NotifyResult.error_code` rather than letting it escape (§4.1).
        """
        if not request.user_id:
            raise InvalidNotification("user_id is required")
        if not request.title and not request.body:
            raise InvalidNotification("a notification needs a title or a body")
        # Not a security check (§4.4): an unrecognised category degrades to "record it anyway"
        # rather than losing the notification over a labeling gap.
        category = request.category if self._category_validator.is_known(request.category) else (
            request.category or "uncategorized"
        )
        notification = Notification(
            notification_id=new_notification_id(),
            user_id=request.user_id,
            category=category,
            title=request.title,
            body=request.body,
            reference=request.reference,
            created_at=utcnow(),
        )
        conn = self._conn_for(request.user_id)
        try:
            with self._lock:
                conn.execute(
                    INSERT_NOTIFICATION_SQL,
                    (
                        notification.notification_id,
                        notification.user_id,
                        notification.category,
                        notification.title,
                        notification.body,
                        notification.reference,
                        None,
                        to_storage_ts(notification.created_at),
                    ),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001 - a write failure here must not escape raw
            self._metrics.increment("notifications_creation_failed")
            raise StoreUnavailable(str(exc)) from exc
        self._metrics.increment("notifications_created")
        return notification

    # ------------------------------------------------------------------- read
    def query(self, query: InboxQuery) -> InboxQueryResult:
        """Return matching notifications, newest first. Never raises — every path returns a
        result carrying `error_code` (`docs/PRINCIPLES.md` §4.1)."""
        if query.limit < 0:
            return InboxQueryResult(
                error_code=code_for(InvalidQuery()), error_detail="limit must not be negative"
            )
        if not query.user_id:
            return InboxQueryResult(
                error_code=code_for(InvalidQuery()), error_detail="user_id is required"
            )
        try:
            self.authorize(query.requesting_user_id, query.user_id)
        except (CrossUserAccessDenied, AccessCheckUnavailable) as exc:
            self._metrics.increment("inbox_reads_denied")
            return InboxQueryResult(error_code=code_for(exc), error_detail=str(exc))

        try:
            conn = self._conn_for(query.user_id)
            where = " AND read_at IS NULL" if query.unread_only else ""
            with self._lock:
                total = conn.execute(
                    f"SELECT COUNT(*) AS n FROM notifications WHERE user_id = ?{where}",
                    (query.user_id,),
                ).fetchone()["n"]
                rows = conn.execute(
                    f"SELECT * FROM notifications WHERE user_id = ?{where}"
                    " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (query.user_id, max(1, query.limit) if query.limit else 100, query.offset),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001 - unanticipated failure becomes data, not a raise
            return InboxQueryResult(error_code="READ_FAILED", error_detail=str(exc))

        self._metrics.increment("inbox_reads_served")
        return InboxQueryResult(
            notifications=tuple(row_to_notification(r) for r in rows),
            total_matching=int(total),
        )

    def mark_read(self, requesting_user_id: str | None, notification_id: str) -> MarkReadResult:
        """Mark one of the *requester's own* notifications read.

        Deliberately no cross-user variant: marking read is a personal preference on one's
        own inbox, not a read of someone else's data, so this always resolves against
        `requesting_user_id` and never accepts a separate `user_id` to act against.
        """
        if requesting_user_id is None:
            return MarkReadResult(
                ok=False,
                error_code=code_for(CrossUserAccessDenied()),
                error_detail="an unresolvable caller cannot mark anything read",
            )
        try:
            conn = self._conn_for(requesting_user_id)
            with self._lock:
                cur = conn.execute(
                    "UPDATE notifications SET read_at = ? WHERE notification_id = ?"
                    " AND user_id = ? AND read_at IS NULL",
                    (to_storage_ts(utcnow()), notification_id, requesting_user_id),
                )
                conn.commit()
                changed = cur.rowcount
        except Exception as exc:  # noqa: BLE001
            return MarkReadResult(ok=False, error_code="STORE_UNAVAILABLE", error_detail=str(exc))

        if changed == 0:
            exc = NotificationNotFound(notification_id)
            return MarkReadResult(
                ok=False, notification_id=notification_id,
                error_code=code_for(exc), error_detail=str(exc),
            )
        self._metrics.increment("inbox_marked_read")
        return MarkReadResult(ok=True, notification_id=notification_id)

    def close(self) -> None:
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()


__all__ = [
    "AuthBreakGlassChecker",
    "DenyCrossUser",
    "InboxStore",
    "PermissiveCategoryValidator",
    "new_notification_id",
]
