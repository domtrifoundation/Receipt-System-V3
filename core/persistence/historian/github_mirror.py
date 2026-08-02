"""Optional off-site mirror of both Historian tracks (`v3-deepdive-29-historian.md` §10).

An export for anyone who wants off-site durability or `git log`-style browsing, run as a
Background Worker idle-time job. **Never a dependency the core write path relies on** — that
distinction is load-bearing: V2 committed the workbook, archive and inbox to git on *every*
write, which is exactly the coupling Historian's same-transaction design replaced. If this
mirror is unreachable, misconfigured, or absent, canonical writes are unaffected.

**Commit granularity, resolved (§14 there): one commit per contribution-review decision, not
per individual field change.** A single approve/reject action on a `Contribution` is one
commit even when it touched several fields, so the git history reads as a real decision log
rather than a field-by-field diff stream that obscures what was actually being decided.

`git` itself sits behind this one module — nothing else in the repository shells out to it.
Its absence is a degradation (mirroring unavailable), never a failure.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contracts import HistorianEvent, HistoryEntry, NarrativeEvent


@dataclass(frozen=True)
class MirrorResult:
    ok: bool
    commit_written: bool = False
    entries_written: int = 0
    error_detail: str = ""


def _entry_to_json(entry: HistoryEntry) -> dict:
    if isinstance(entry, HistorianEvent):
        return {
            "track": "data_change",
            "event_id": entry.event_id,
            "table": entry.table_name,
            "row_id": entry.row_id,
            "before": dict(entry.before) if entry.before is not None else None,
            "after": dict(entry.after) if entry.after is not None else None,
            "actor": entry.actor,
            "program_version": entry.program_version,
            "occurred_at": entry.occurred_at.isoformat(),
        }
    assert isinstance(entry, NarrativeEvent)
    return {
        "track": "narrative",
        "event_id": entry.event_id,
        "receipt_id": entry.receipt_id,
        "run_id": entry.run_id,
        "stage": entry.stage.value,
        "summary": entry.summary,
        "detail": dict(entry.detail),
        "triggered_by": entry.triggered_by,
        "occurred_at": entry.occurred_at.isoformat(),
    }


class GitHubMirror:
    """Writes one decision's worth of history into a local git repo and commits it."""

    def __init__(self, repo_dir: Path | str) -> None:
        self._repo = Path(repo_dir)

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - fixed argv, never a shell string
            ["git", *args], cwd=self._repo, capture_output=True, text=True, check=False
        )

    def is_available(self) -> bool:
        """`git` present and the target a real repo. Absence degrades, never crashes."""
        if not self._repo.exists():
            return False
        try:
            return self._git("rev-parse", "--git-dir").returncode == 0
        except (OSError, FileNotFoundError):
            return False

    def mirror_decision(
        self, decision_id: str, entries: tuple[HistoryEntry, ...], message: str
    ) -> MirrorResult:
        """One reviewable decision → one commit, both tracks interleaved as written."""
        if not self.is_available():
            return MirrorResult(ok=False, error_detail="git or mirror repo unavailable")
        if not entries:
            return MirrorResult(ok=True, commit_written=False)
        path = self._repo / "history" / f"{decision_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [_entry_to_json(e) for e in entries]
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        add = self._git("add", str(path.relative_to(self._repo)))
        if add.returncode != 0:
            return MirrorResult(ok=False, error_detail=add.stderr.strip())
        commit = self._git("commit", "-m", message)
        if commit.returncode != 0:
            return MirrorResult(ok=False, error_detail=commit.stderr.strip())
        return MirrorResult(ok=True, commit_written=True, entries_written=len(entries))


__all__ = ["GitHubMirror", "MirrorResult"]
