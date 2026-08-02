"""The review-decision trail (`v3-deepdive-40-temporal-learning.md` §6).

**A deliberate deviation from that section, flagged rather than quietly taken.** §6 as
written describes this as "a parallel git-tracked mirror" so review decisions are visible
as a diff. That approach was scoped and reversed: `docs/MAINTENANCE.md` §4 records the
identical idea being dropped for Historian once it was clear a parallel git record buys
none of git's real benefits when the live queryable data was never going to be git-tracked
anyway, and this folder's own `CLAUDE.md` states the reversal applies here too — the
moderation queue is a plain table in the same queryable database, not git. This module is
therefore the *content* §6 wanted (an append-only, human-readable, diffable record of the
review process itself) without the git mechanism §6 assumed. Anyone re-reading §6 and
wondering where the git integration went should read this paragraph, not go build it.

**Append-only structurally, not by convention** (`docs/PRINCIPLES.md` §2.3). There is no
`update` or `delete` on this class's public surface, and `entries()` hands back a tuple of
frozen records. An audit trail's entire value is being trustworthy in exactly the scenario
where someone would like to quietly alter it, so the absence of those methods is the
guarantee — not a note asking callers not to.

`render()` produces the diffable text form: stable field order, one entry per block, so
two renderings of the same trail differ only where the trail itself grew.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from common.frozen_dict import FrozenDict

from .contracts import Contribution, ReviewDecision, utcnow


@dataclass(frozen=True)
class MirrorEntry:
    """One recorded step of the review process.

    `event` is deliberately coarse — `submitted`, `prescreened`, `decided`, `merged` — so
    the trail reads as a lifecycle rather than a field-level change log. Field-level
    history of the entity itself is Historian's job, through Persistence's write path;
    duplicating it here would create a second place the same facts can disagree.
    """

    contribution_id: str
    event: str
    actor: str
    at: datetime
    detail: FrozenDict = field(default_factory=lambda: FrozenDict({}))


class ReviewAuditMirror:
    """Append-only trail of everything that happened to a contribution.

    The list is a genuinely mutable internal structure appended to at runtime, so it is a
    plain `list` — every element in it is a frozen record and every collection handed out
    is a tuple, which is where the immutability that matters actually lives.
    """

    def __init__(self) -> None:
        self._entries: list[MirrorEntry] = []

    def record_submission(self, contribution: Contribution) -> MirrorEntry:
        return self._append(
            contribution.contribution_id,
            "submitted",
            contribution.contributor,
            FrozenDict(
                {
                    "entity_type": contribution.target_entity_type,
                    "target_entity_id": contribution.target_entity_id or "",
                    "staff_review_status": contribution.staff_review_status,
                    "curation_type": contribution.curation_type or "",
                }
            ),
        )

    def record_prescreen(self, contribution: Contribution, verdict: str, actor: str = "llm") -> MirrorEntry:
        return self._append(
            contribution.contribution_id, "prescreened", actor, FrozenDict({"verdict": verdict})
        )

    def record_decision(self, decision: ReviewDecision) -> MirrorEntry:
        """A rejection is recorded exactly as fully as an approval.

        The rejected proposals are frequently the more interesting half of a review trail:
        they are what someone auditing a moderator's judgement actually wants to read.
        """
        return self._append(
            decision.contribution_id,
            "decided",
            f"human:{decision.reviewer}",
            FrozenDict(
                {"approved": decision.approved, "reason": decision.reason}
            ),
            at=decision.decided_at,
        )

    def record_merge(self, contribution: Contribution, entity_id: str) -> MirrorEntry:
        return self._append(
            contribution.contribution_id,
            "merged",
            contribution.contributor,
            FrozenDict({"entity_id": entity_id}),
        )

    def _append(
        self,
        contribution_id: str,
        event: str,
        actor: str,
        detail: FrozenDict,
        at: datetime | None = None,
    ) -> MirrorEntry:
        entry = MirrorEntry(
            contribution_id=contribution_id, event=event, actor=actor,
            at=at or utcnow(), detail=detail,
        )
        self._entries.append(entry)
        return entry

    # ------------------------------------------------------------------------ reads

    def entries(self) -> tuple[MirrorEntry, ...]:
        return tuple(self._entries)

    def for_contribution(self, contribution_id: str) -> tuple[MirrorEntry, ...]:
        return tuple(e for e in self._entries if e.contribution_id == contribution_id)

    def render(self) -> str:
        """The diffable text form §6 actually wanted, without the git mechanism.

        Field order is fixed and detail keys are sorted, so an added review step shows up
        as added lines and nothing else moves — which is the only property that made a
        git-tracked version attractive in the first place.
        """
        blocks: list[str] = []
        for entry in self._entries:
            lines = [
                f"contribution: {entry.contribution_id}",
                f"  event: {entry.event}",
                f"  actor: {entry.actor}",
                f"  at: {entry.at.isoformat()}",
            ]
            lines.extend(f"  {k}: {entry.detail[k]}" for k in sorted(entry.detail))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["MirrorEntry", "ReviewAuditMirror"]
