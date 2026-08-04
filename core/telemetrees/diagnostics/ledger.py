"""Persisted record of every issue this install has ever filed — the same small-JSON-
per-API pattern `common/local_config_store.py` centralizes, extended here to a list of
records rather than a flat dict of scalars (`LocalConfigStore` itself stays scalar-only;
duplicating its lock/read/write shape for a list is simpler than bending its own contract
to fit a second shape).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from .contracts import FiledIssueRecord

__all__ = ["FiledIssueLedger"]

RELPATH = "telemetrees/filed_issues.json"


class FiledIssueLedger:
    def __init__(self, install_root: Path | str) -> None:
        self._path = Path(install_root) / RELPATH
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _write(self, records: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    def record(self, entry: FiledIssueRecord) -> None:
        """Real, additive filing — never overwrites an existing entry for the same
        `fingerprint`, since a second detection of the same underlying problem should
        link back to the issue already open for it, not create a duplicate ledger row
        (whether the *detector* actually enforces that dedupe is that future component's
        own job; this method just refuses to duplicate its own record for a fingerprint
        already on file)."""
        with self._lock:
            records = self._read()
            if any(r["fingerprint"] == entry.fingerprint for r in records):
                return
            records.append({
                "fingerprint": entry.fingerprint, "issue_number": entry.issue_number,
                "url": entry.url, "title": entry.title, "filed_at": entry.filed_at.isoformat(),
            })
            self._write(records)

    def list_all(self) -> tuple[FiledIssueRecord, ...]:
        with self._lock:
            records = self._read()
        return tuple(
            FiledIssueRecord(
                fingerprint=r["fingerprint"], issue_number=r["issue_number"], url=r["url"],
                title=r["title"], filed_at=datetime.fromisoformat(r["filed_at"]),
            )
            for r in records
        )
