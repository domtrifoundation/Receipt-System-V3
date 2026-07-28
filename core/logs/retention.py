"""Retention sweeps (§5, §10) — two windows, both enforced by deleting whole day files.

**Not in the deep-dive's §2 package layout**, added because §5 describes a real capability
with its own policy and the alternative placements were both wrong: in `writer.py` it would
put deletion on a path whose entire storage argument is "pure append, no in-place rewrite
ever", and in `index.py` it would make the query accelerator responsible for the lifetime of
the data it merely points at.

The two windows:

- **90 days** for ordinary operational trace. Unlike Audit's retention — explicitly left as a
  legal/business question in its own deep-dive — this is a pure operational-cost tradeoff
  (disk space against debugging lookback), so a default is reasonable to set here.
- **7 days for TRACE-tier entries** (§10's resolved answer to TRACE volume at real scale).
  Raw OCR/LLM output is useful for immediate debugging, not as a long-term record.

This is called by a Background Workers idle-time job, never on the write path. It never
touches today's files: a sweep that could delete the file a running service currently holds
open would make retention able to break logging, which is the one thing this API must not do.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .contracts import PurgeResult, RetentionPolicy
from .index import LogIndex
from .metrics import LogsMetricsCollector
from .paths import default_log_root, describe, iter_log_files


def expired_files(
    root: Path,
    policy: RetentionPolicy,
    *,
    today: date | None = None,
) -> tuple[Path, ...]:
    """Which files are past their own window. Pure — decides nothing about deleting.

    Separated from the deletion itself so a retention policy can be inspected ("what would
    this sweep remove?") without a caller having to trust a dry-run flag on a destructive
    function.
    """
    today = today or date.today()
    doomed: list[Path] = []
    for path in iter_log_files(root):
        described = describe(path)
        if described is None:  # pragma: no cover - iter_log_files already filters these
            continue
        _service, day, is_trace = described
        window = policy.trace_retention_days if is_trace else policy.retention_days
        if day <= today - timedelta(days=max(window, 0)) and day < today:
            doomed.append(path)
    return tuple(doomed)


def purge(
    root: Path | str | None = None,
    policy: RetentionPolicy | None = None,
    *,
    index: LogIndex | None = None,
    metrics: LogsMetricsCollector | None = None,
    today: date | None = None,
) -> PurgeResult:
    """Delete expired files and prune the index rows that pointed at them.

    Order matters: the file goes first, then its index rows. The reverse order would leave a
    window where the index says an entry does not exist while the file still holds it — and
    §3.2's whole claim is that the index never contradicts the files, only points into them.
    A file that cannot be deleted is reported and skipped, never retried in a loop that could
    stall an idle-time worker.
    """
    root = Path(root) if root else default_log_root()
    policy = policy or RetentionPolicy()
    deleted: list[str] = []
    failures: list[str] = []

    for path in expired_files(root, policy, today=today):
        try:
            path.unlink()
        except OSError as exc:
            failures.append(f"{path}: {exc}")
            continue
        deleted.append(str(path))
        if metrics is not None:
            metrics.increment("files_purged")

    pruned = index.prune_paths(tuple(deleted)) if index is not None and deleted else 0

    if failures:
        return PurgeResult(
            files_deleted=tuple(deleted),
            index_rows_pruned=pruned,
            error_code="PURGE_INCOMPLETE",
            error_detail="; ".join(failures),
        )
    return PurgeResult(files_deleted=tuple(deleted), index_rows_pruned=pruned)


__all__ = ["expired_files", "purge"]
