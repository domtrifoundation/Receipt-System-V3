"""The JSON Lines wire format for a `LogEntry` (§3.1) — one codec, both directions.

**Not in the deep-dive's §2 package layout.** Encoding lives on the write path and decoding
lives on the read path, so the obvious placement would have been half in `writer.py` and half
in `query.py` — two independently-maintained opinions about the same file format, which is
precisely the drift this project keeps correcting elsewhere. One module owns the format;
`writer` and `query` both call it.

Two properties this codec has to hold, because the storage design leans on them:

- **A line is self-contained.** The index stores a byte offset and length; reading an entry
  is a seek and a single line read, with no dependence on anything earlier in the file.
- **A corrupt line is skipped, not fatal.** A process killed mid-append can leave a partial
  final line. Losing that one entry is the correct outcome; failing an entire query or an
  index rebuild because of it is not (`docs/PRINCIPLES.md` §4.4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from common.frozen_dict import FrozenDict

from .contracts import LogEntry, LogLevel

ENCODING = "utf-8"


def encode(entry: LogEntry) -> bytes:
    """One entry as a single UTF-8 JSONL line, newline included.

    `ensure_ascii=True` is deliberate: receipt text is routinely non-ASCII (Filipino vendor
    names, peso signs), and escaping it keeps a line's byte length independent of whatever
    encoding a future reader opens the file with.
    """
    payload = {
        "ts": entry.timestamp.isoformat(),
        "run_id": entry.run_id,
        "user_id": entry.user_id,
        "service": entry.service,
        "level": entry.level.value,
        "message": entry.message,
        # Written whenever it exists, at every verbosity tier without exception (§3.3).
        "traceback": entry.traceback,
        "context": dict(entry.context),
    }
    return (json.dumps(payload, default=str) + "\n").encode(ENCODING)


def decode(line: bytes | str) -> LogEntry | None:
    """One JSONL line back into a `LogEntry`, or `None` if the line is not one.

    Returns `None` rather than raising for a truncated or malformed line — see the module
    docstring. An unknown `level` string is also `None`: a file written by a newer version
    that added a level is readable up to that entry, and the entries around it still are.
    """
    if isinstance(line, bytes):
        try:
            line = line.decode(ENCODING)
        except UnicodeDecodeError:
            return None
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, Mapping):
        return None
    try:
        level = LogLevel(raw["level"])
        timestamp = datetime.fromisoformat(raw["ts"])
    except (KeyError, ValueError):
        return None
    context = raw.get("context")
    return LogEntry(
        timestamp=timestamp,
        run_id=raw.get("run_id"),
        user_id=raw.get("user_id"),
        service=raw.get("service", "unknown"),
        level=level,
        message=raw.get("message", ""),
        traceback=raw.get("traceback"),
        # `Mapping`, never `dict`: the 3.15 builtin `frozendict` inherits from `object`,
        # so an `isinstance(..., dict)` guard here silently takes the empty-context branch
        # for exactly the type this API's own contracts use (`docs/PRINCIPLES.md` §2.1).
        context=FrozenDict(context if isinstance(context, Mapping) else {}),
    )


__all__ = ["ENCODING", "decode", "encode"]
