"""Which release directory is active, per channel (`v3-deepdive-38-supervisor.md` §3.1) —
"a small local record (not a full database — this is genuinely simple state)."

**Persisted as one small JSON file**, not a database — matching the deep-dive's own
explicit "not a full database" framing, and the same shape `services/update/
release_manager.py`'s own `CHANNEL_HISTORY_RELPATH` record already uses for its own
simple, real, persisted state. Lives at the top level (`<install-root>/supervisor/
active_releases.json`), a sibling of every release clone, never inside one — Supervisor
itself is a permanent top-level citizen (`docs/PRINCIPLES.md` §1.6) and its own state
lives at the same level it does.

**Keeps one prior release per channel, not full history** — exactly what §3.3's rollback
needs ("reverts... back to the prior release directory, still on disk — garbage
collection always keeps at least one prior") and nothing more; a full audit trail of
every past cutover is a different, not-yet-needed concern.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from .contracts import ActiveRelease, utcnow
from .errors import UnknownChannel

__all__ = ["ACTIVE_RELEASES_RELPATH", "ChannelArbitrator"]

#: Relative to the install root (`<install-root>/supervisor/`, Supervisor's own permanent
#: top-level home — see the module docstring).
ACTIVE_RELEASES_RELPATH = Path("supervisor") / "active_releases.json"


class ChannelArbitrator:
    """The real, persisted per-channel active-release record. One instance per
    Supervisor process; safe for concurrent access via a real lock (this project targets
    free-threaded 3.14t, `docs/PRINCIPLES.md` §3.3.1)."""

    def __init__(self, install_root: Path | str) -> None:
        self._install_root = Path(install_root)
        self._path = self._install_root / ACTIVE_RELEASES_RELPATH
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self._path.is_file():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def get_active(self, channel: str) -> ActiveRelease | None:
        with self._lock:
            data = self._read()
        entry = data.get(channel)
        if entry is None:
            return None
        return ActiveRelease(
            channel=channel, release_dir=Path(entry["release_dir"]),
            activated_at=datetime.fromisoformat(entry["activated_at"]),
        )

    def require_active(self, channel: str) -> ActiveRelease:
        found = self.get_active(channel)
        if found is None:
            raise UnknownChannel(channel)
        return found

    def all_active(self) -> tuple[ActiveRelease, ...]:
        with self._lock:
            data = self._read()
        releases = [
            ActiveRelease(
                channel=channel, release_dir=Path(entry["release_dir"]),
                activated_at=datetime.fromisoformat(entry["activated_at"]),
            )
            for channel, entry in data.items()
        ]
        return tuple(sorted(releases, key=lambda r: r.channel))

    def prior_release(self, channel: str) -> Path | None:
        """The release directory this channel was on immediately before its current
        one, or `None` if this channel has never been cut over (only ever had one
        activation)."""
        with self._lock:
            data = self._read()
        entry = data.get(channel)
        if entry is None or not entry.get("prior_release_dir"):
            return None
        return Path(entry["prior_release_dir"])

    def set_active(self, channel: str, release_dir: Path | str) -> ActiveRelease:
        """Cuts `channel` over to `release_dir`. The previously-active directory (if any)
        becomes this channel's own `prior_release_dir` — what `rollback.py` reverts to."""
        release_dir = Path(release_dir)
        now = utcnow()
        with self._lock:
            data = self._read()
            existing = data.get(channel)
            prior = existing["release_dir"] if existing else None
            data[channel] = {
                "release_dir": str(release_dir),
                "activated_at": now.isoformat(),
                "prior_release_dir": prior,
            }
            self._write(data)
        return ActiveRelease(channel=channel, release_dir=release_dir, activated_at=now)
