"""The real "which versions are available for this service" record — the configuration
an owner sets in the TUI's Fleet & Updates screen, and the ceiling the webapp's own
version choice for end users is bounded by. A genuinely different concept from
`version_pins.py`'s own `VersionPinStore`: a pin *forces* one specific version, overriding
the channel's normal release; this store tracks the *set* of versions a service is allowed
to run concurrently at all, most of which have no pin and follow the channel normally.

**Interface API and Inference API are the two single-instance exceptions** — the same
closed list `single_instance.py`'s own module docstring names. Every other service can
have multiple versions available at once, each started dynamically on real demand
(`dynamic_start.py`); these two can only ever have exactly one, since only one instance
of either can run at a time. `set_available` enforces this structurally rather than
trusting every caller to remember it.

Persisted the same small-JSON-file way every other piece of Supervisor's own durable
state is (`arbitration.py`'s `ChannelArbitrator`, `version_pins.py`'s `VersionPinStore`)
— genuinely simple state, never a database.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

__all__ = ["AVAILABLE_VERSIONS_RELPATH", "SINGLE_INSTANCE_SERVICES", "AvailableVersionsStore", "is_single_instance"]

AVAILABLE_VERSIONS_RELPATH = Path("supervisor") / "available_versions.json"

#: The same closed, explicitly-justified list `single_instance.py`'s own docstring names
#: (§5.3) — only these two services can ever have a single running instance, never
#: multiple concurrent versions.
SINGLE_INSTANCE_SERVICES: frozenset[str] = frozenset({"interface_tui", "inference"})


def _key(channel: str, service_name: str) -> str:
    return f"{channel}::{service_name}"


class AvailableVersionsStore:
    def __init__(self, install_root: Path | str) -> None:
        self._install_root = Path(install_root)
        self._path = self._install_root / AVAILABLE_VERSIONS_RELPATH
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

    def set_available(self, channel: str, service_name: str, versions: tuple[str, ...]) -> tuple[str, ...]:
        """Sets the real, complete list of versions available for `service_name` on
        `channel`. For `SINGLE_INSTANCE_SERVICES`, only the *last* version in `versions`
        is kept — a real, structural enforcement of "only one tagged version, ever,"
        not a convention the caller has to remember. Returns what was actually stored.
        """
        deduped = tuple(dict.fromkeys(v for v in versions if v))
        if service_name in SINGLE_INSTANCE_SERVICES:
            deduped = deduped[-1:] if deduped else ()
        with self._lock:
            data = self._read()
            key = _key(channel, service_name)
            if deduped:
                data[key] = {"channel": channel, "service_name": service_name, "versions": list(deduped)}
            else:
                data.pop(key, None)
            self._write(data)
        return deduped

    def get_available(self, channel: str, service_name: str) -> tuple[str, ...]:
        with self._lock:
            data = self._read()
        entry = data.get(_key(channel, service_name))
        return tuple(entry["versions"]) if entry else ()

    def list_all(self, channel: str) -> dict[str, tuple[str, ...]]:
        with self._lock:
            data = self._read()
        return {
            entry["service_name"]: tuple(entry["versions"])
            for entry in data.values()
            if entry["channel"] == channel
        }


def is_single_instance(service_name: str) -> bool:
    return service_name in SINGLE_INSTANCE_SERVICES
