"""One small persisted JSON file per owning API for that API's own genuinely simple,
non-relational operational settings (tenancy mode, opt-in flags, channel choice) — the
exact pattern `supervisor/arbitration.py`'s `ChannelArbitrator`, `supervisor/version_
pins.py`'s `VersionPinStore`, and `supervisor/available_versions.py`'s `AvailableVersions
Store` already established independently. Centralized here rather than reimplemented a
sixth time, since the read/write/lock shape is identical every time: a `dict` of
JSON-serializable values, read-modify-write under a lock, missing file means "no value
set yet" rather than an error.

**Not a shared taxonomy or schema store** — `docs/PRINCIPLES.md` §3.4's "any new typed,
learned, or schema data goes through Architect API" rule is about domain data (vendor
taxonomy, learned corrections), not an individual API's own plain config flags. Each
caller gets its own file under `<install_root>/<relpath>`, never a shared table another
API could accidentally read or corrupt.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

__all__ = ["LocalConfigStore"]


class LocalConfigStore:
    def __init__(self, install_root: Path | str, relpath: Path | str) -> None:
        self._path = Path(install_root) / Path(relpath)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def get_all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._read())
