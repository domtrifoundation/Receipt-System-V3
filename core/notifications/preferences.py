"""Per-user channel opt-in (§5) — read and write, over the same per-user database `inbox.py`
uses for the notifications table itself (`db.py`'s own docstring explains the file placement).

**Opt-in, not opt-out, is enforced here, not just documented.** `is_enabled` returns `False`
for any channel this user has no row for — there is no "assume enabled until told otherwise"
branch anywhere in this module, which is what makes the deep-dive's own "a user who never
enabled email/SMS delivery only ever sees in-app notifications" an actual guarantee rather
than a default that could quietly flip.

Reads and writes here are **always own-user** — a channel preference is exactly the kind of
personal setting that a client-role user manages for themself, never a break-glass read
target the way an inbox's *content* can be (`inbox.py`'s cross-user gate does not apply here;
this module has no notion of `requesting_user_id` at all). `service.py` is what would refuse a
caller trying to set another user's preference, by never accepting a second user id on this
surface in the first place.
"""

from __future__ import annotations

import threading
from pathlib import Path

from .contracts import KNOWN_CHANNELS, ChannelPreference, PreferencesResult, SetPreferenceResult
from .db import connect, default_db_path, row_to_preference
from .errors import InvalidPreference, code_for


class PreferenceStore:
    """One store per process, one connection per user id touched — mirrors
    `inbox.InboxStore`'s own per-user connection cache, and deliberately reuses the identical
    sqlite file rather than opening a second one per user (`db.py`)."""

    def __init__(self, top_level: Path | str | None = None) -> None:
        self._top_level = top_level
        self._lock = threading.Lock()
        self._connections: dict[str, object] = {}

    def _conn_for(self, user_id: str):
        with self._lock:
            conn = self._connections.get(user_id)
            if conn is None:
                conn = connect(default_db_path(user_id, top_level=self._top_level))
                self._connections[user_id] = conn
            return conn

    def get_all(self, user_id: str) -> PreferencesResult:
        """Every known channel's preference for this user, defaulting to disabled for any
        channel with no stored row — the opt-in guarantee this module's own docstring states."""
        if not user_id:
            return PreferencesResult(
                error_code=code_for(InvalidPreference()), error_detail="user_id is required"
            )
        try:
            conn = self._conn_for(user_id)
            with self._lock:
                rows = {
                    r["channel"]: row_to_preference(r)
                    for r in conn.execute(
                        "SELECT * FROM channel_preferences WHERE user_id = ?", (user_id,)
                    ).fetchall()
                }
        except Exception as exc:  # noqa: BLE001
            return PreferencesResult(error_code="STORE_UNAVAILABLE", error_detail=str(exc))

        resolved = tuple(
            rows.get(channel, ChannelPreference(user_id=user_id, channel=channel, enabled=False))
            for channel in KNOWN_CHANNELS
        )
        return PreferencesResult(preferences=resolved)

    def is_enabled(self, user_id: str, channel: str) -> bool:
        """The single question `dispatch.py` actually needs answered, without a caller having
        to fetch every channel and search it — the opt-in default is identical either way."""
        result = self.get_all(user_id)
        if not result.ok:
            return False  # a store failure degrades to "do not send", never to "send anyway"
        return any(p.channel == channel and p.enabled for p in result.preferences)

    def set(
        self, user_id: str, channel: str, enabled: bool, contact_override: str | None = None
    ) -> SetPreferenceResult:
        if channel not in KNOWN_CHANNELS:
            exc = InvalidPreference(f"unknown channel {channel!r}")
            return SetPreferenceResult(ok=False, error_code=code_for(exc), error_detail=str(exc))
        if not user_id:
            exc = InvalidPreference("user_id is required")
            return SetPreferenceResult(ok=False, error_code=code_for(exc), error_detail=str(exc))

        preference = ChannelPreference(
            user_id=user_id, channel=channel, enabled=enabled,
            contact_override=contact_override,
        )
        try:
            conn = self._conn_for(user_id)
            with self._lock:
                conn.execute(
                    "INSERT INTO channel_preferences (user_id, channel, enabled,"
                    " contact_override) VALUES (?,?,?,?)"
                    " ON CONFLICT(user_id, channel) DO UPDATE SET"
                    " enabled = excluded.enabled, contact_override = excluded.contact_override",
                    (user_id, channel, int(enabled), contact_override),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            return SetPreferenceResult(
                ok=False, error_code="STORE_UNAVAILABLE", error_detail=str(exc)
            )
        return SetPreferenceResult(ok=True, preference=preference)

    def close(self) -> None:
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()


__all__ = ["PreferenceStore"]
