"""§5.2's own per-API, per-channel version pinning — "a real, more surgical alternative
to a full `TriggerRollback`... useful for exactly the case a full rollback is too blunt
for." Not in the deep-dive's own §2 package layout, added for the same reason
`single_instance.py` was: real, substantial logic that belongs in its own module rather
than folded into `service.py`'s thin gRPC adapter.

**Persisted the same small-JSON-file way `arbitration.py`'s own `ChannelArbitrator`
is** — "genuinely simple state," never a database, matching this whole package's own
established shape for its few pieces of durable state.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from .contracts import ServiceVersionPin, utcnow

__all__ = ["VERSION_PINS_RELPATH", "VersionPinStore"]

VERSION_PINS_RELPATH = Path("supervisor") / "version_pins.json"


def _key(channel: str, service_name: str) -> str:
    return f"{channel}::{service_name}"


class VersionPinStore:
    """The real, persisted pin record. `pinned_version=None` clears a pin back to
    "follow the channel normally" (§5.2's own default, unpinned state) — deleting the
    entry rather than storing a null, so `list_pins()` only ever returns genuinely active
    pins."""

    def __init__(self, install_root: Path | str) -> None:
        self._install_root = Path(install_root)
        self._path = self._install_root / VERSION_PINS_RELPATH
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

    def set_pin(self, channel: str, service_name: str, pinned_version: str | None, *, pinned_by: str) -> ServiceVersionPin | None:
        """Returns the new pin, or `None` if `pinned_version=None` cleared an existing
        one (or there was nothing to clear)."""
        now = utcnow()
        with self._lock:
            data = self._read()
            key = _key(channel, service_name)
            if pinned_version is None:
                data.pop(key, None)
                self._write(data)
                return None
            data[key] = {
                "channel": channel, "service_name": service_name, "pinned_version": pinned_version,
                "pinned_by": pinned_by, "pinned_at": now.isoformat(),
            }
            self._write(data)
        return ServiceVersionPin(
            channel=channel, service_name=service_name, pinned_version=pinned_version,
            pinned_by=pinned_by, pinned_at=now,
        )

    def get_pin(self, channel: str, service_name: str) -> ServiceVersionPin | None:
        with self._lock:
            data = self._read()
        entry = data.get(_key(channel, service_name))
        if entry is None:
            return None
        return _entry_to_pin(entry)

    def list_pins(self, channel: str | None = None) -> tuple[ServiceVersionPin, ...]:
        """Every active pin, or every pin on `channel` when given — §7's own "surgical,
        not a full rollback" claim is checkable directly here: a pin on one service
        never appears against any other service on the same channel."""
        with self._lock:
            data = self._read()
        pins = [_entry_to_pin(entry) for entry in data.values()]
        if channel is not None:
            pins = [p for p in pins if p.channel == channel]
        return tuple(sorted(pins, key=lambda p: (p.channel, p.service_name)))


def _entry_to_pin(entry: dict) -> ServiceVersionPin:
    return ServiceVersionPin(
        channel=entry["channel"], service_name=entry["service_name"], pinned_version=entry["pinned_version"],
        pinned_by=entry["pinned_by"], pinned_at=datetime.fromisoformat(entry["pinned_at"]),
    )
