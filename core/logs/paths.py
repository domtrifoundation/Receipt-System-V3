"""Where log files live, and how a path decodes back into what it holds.

**Not in the deep-dive's §2 package layout** — added because four modules (`writer`, `index`,
`query`, `retention`) all need the same answer to "which file does this belong in", and the
alternative was three of them importing it from the fourth, which makes the writer look like
a utility module for the readers.

Two decisions are recorded here rather than left implicit at each call site:

1. **The log root is never inside the repository or a release clone** (`docs/PRINCIPLES.md`
   §1.6, §2.4). Logs contain real receipt content — OCR text, LLM prompts quoting actual
   receipt data — and V2's own defaulting of data paths inside the program directory is
   exactly the mistake that rule exists to prevent.

2. **TRACE entries get their own sibling file per service per day.** §10 resolves TRACE-tier
   volume with a shorter retention window (7 days) than everything else (90). Purging only
   the trace lines out of a mixed file would mean rewriting that file in place, and §3.1's
   whole storage argument is that a log file is a pure append with no in-place rewrite ever.
   Splitting the tier into `<day>.trace.jsonl` makes the shorter TTL a plain file delete —
   §10's "just a shorter TTL for that one verbosity tier, not a whole separate rotation
   mechanism", since rotation is still one file per service per day, only two tracks of it.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path

from .contracts import LogLevel

#: `<service>/<YYYY-MM-DD>[.trace].jsonl`
_DAY_FILE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})(?P<trace>\.trace)?\.jsonl$")

TRACE_SUFFIX = ".trace"


def default_log_root() -> Path:
    """The log root, resolved from the environment, never from a repo-relative default.

    `RESIBO_LOG_ROOT` wins when set (a self-hosted install pointing logs at its own volume).
    `RESIBO_TOP_LEVEL` is how Supervisor tells a service where the shared top-level
    installation directory is; logs sit under it as a sibling of every release clone. The
    final fallback keeps a bare developer checkout runnable while still resolving *outside*
    the repository rather than into `data/`.
    """
    explicit = os.environ.get("RESIBO_LOG_ROOT")
    if explicit:
        return Path(explicit)
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "logs"


def is_trace_tier(level: LogLevel) -> bool:
    """Whether an entry belongs in the short-retention track (§10)."""
    return level is LogLevel.TRACE


def day_file(root: Path, service: str, when: datetime | date, *, trace: bool = False) -> Path:
    """The file one entry appends to. Day-rotated: a new file at the day boundary, no
    truncation logic anywhere (§3.1)."""
    day = when.date() if isinstance(when, datetime) else when
    suffix = f"{TRACE_SUFFIX}.jsonl" if trace else ".jsonl"
    return root / _safe_service(service) / f"{day.isoformat()}{suffix}"


def file_for_entry(root: Path, service: str, when: datetime, level: LogLevel) -> Path:
    return day_file(root, service, when, trace=is_trace_tier(level))


def describe(path: Path) -> tuple[str, date, bool] | None:
    """Decode `<service>/<day>[.trace].jsonl` back into `(service, day, is_trace)`.

    Returns `None` for anything that is not a log file, so a stray file dropped into the log
    root degrades to being ignored rather than crashing a rebuild or a retention sweep.
    """
    m = _DAY_FILE.match(path.name)
    if not m:
        return None
    try:
        day = date.fromisoformat(m.group("day"))
    except ValueError:  # pragma: no cover - the regex already constrains this
        return None
    return path.parent.name, day, bool(m.group("trace"))


def iter_log_files(root: Path, service: str | None = None):
    """Every JSONL log file under the root, in a stable order.

    Sorted so a rebuild and a query walk files identically — an index whose contents depend
    on filesystem enumeration order would be a rebuild that produces a different answer each
    time, which is the opposite of §3.2's claim.
    """
    if not root.exists():
        return
    services = [root / _safe_service(service)] if service else sorted(
        p for p in root.iterdir() if p.is_dir()
    )
    for service_dir in services:
        if not service_dir.is_dir():
            continue
        for path in sorted(service_dir.iterdir()):
            if path.is_file() and describe(path) is not None:
                yield path


def _safe_service(service: str) -> str:
    """A service name is an internal identifier, but it still becomes a directory name.

    Anything path-significant is replaced rather than sanitised-and-hoped: a service that
    somehow contained a separator would otherwise write outside the log root entirely.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", service or "unknown")
    return cleaned.strip(".") or "unknown"


__all__ = [
    "TRACE_SUFFIX",
    "day_file",
    "default_log_root",
    "describe",
    "file_for_entry",
    "is_trace_tier",
    "iter_log_files",
]
