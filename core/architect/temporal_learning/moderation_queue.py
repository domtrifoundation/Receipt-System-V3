"""The moderation pipeline (`v3-deepdive-40-temporal-learning.md` §6).

Two paths, and the difference between them is the whole design:

- **User-shared contribution** — LLM-prescreen, then a human staff decision, then merge.
- **Staff's own direct-to-global write** (§3.2) — LLM-prescreen, then merge. No second
  staff member approves the first one's submission: that would be a circular gate, and the
  actor's own role already carries the authority. It is still fully recorded, so this is a
  shorter path to the same audit-visible outcome, not a quieter one.

**Nothing merges without prescreen.** If every prescreen provider is unavailable, the
contribution stays pending and says so. That is the one place this API does not degrade in
the usual direction: `docs/PRINCIPLES.md` §4.4 says a missing capability degrades to
unavailable, and here "unavailable" means review takes longer — never that the review step
was skipped, which §4.3's never-silently-override rule forbids outright.

**Prescreen is a Provider Registry** (`docs/PRINCIPLES.md` §1.2) rather than one call,
because the two providers catch genuinely different things: the heuristic screen catches
malformed and duplicate submissions with no dependency at all, and the Inference-backed
screen catches the semantic problems a structural check cannot see. Running both is worth
more than choosing one, so both run and any rejection is decisive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from .audit_mirror import ReviewAuditMirror
from .contracts import (
    Contribution,
    ContributionResult,
    LearningError,
    ReviewDecision,
    utcnow,
)
from .contribution import merge_payload
from .entities import EntityManager, entity_id_of
from .errors import LearningErrorCode, learning_message_for


@dataclass(frozen=True)
class PrescreenVerdict:
    """One provider's opinion. `available=False` means it could not form one at all."""

    provider: str
    passed: bool
    verdict: str
    detail: str = ""
    available: bool = True


def _error(code: str, detail: str = "") -> LearningError:
    return LearningError(code=code, detail=detail or learning_message_for(code))


class PrescreenProvider(Protocol):
    """A pre-review screen. Must never raise: an unavailable screen is a verdict."""

    name: str

    async def prescreen(self, contribution: Contribution) -> PrescreenVerdict: ...


class HeuristicPrescreen:
    """Structural screening with no dependency of any kind.

    Deliberately cheap and always available, so an instance with no Inference capacity
    still gets the obviously-malformed submissions filtered rather than pushing every one
    of them at a human.
    """

    name = "heuristic"

    def __init__(self, required_fields: Mapping[str, tuple[str, ...]] | None = None) -> None:
        # `is None`, never a truthiness test — a caller deliberately supplying an empty
        # mapping (screen nothing structurally) would otherwise silently get the defaults.
        self._required: Mapping[str, tuple[str, ...]] = required_fields if required_fields is not None else {
            "corporation": ("name", "corporate_tin"),
            "branch": ("corporation_id", "address"),
            "franchiser": ("name", "franchiser_tin"),
        }

    async def prescreen(self, contribution: Contribution) -> PrescreenVerdict:
        change = contribution.proposed_change
        if not change:
            return PrescreenVerdict(self.name, False, "malformed", "empty proposed change")
        if contribution.curation_type is not None:
            # A curation candidate proposes a cleanup, not entity fields — screening it
            # against entity required-fields would reject every one of them.
            return PrescreenVerdict(self.name, True, "clean", "curation candidate")
        if contribution.target_entity_id is None:
            missing = [
                f
                for f in self._required.get(contribution.target_entity_type, ())
                if not change.get(f)
            ]
            if missing:
                return PrescreenVerdict(
                    self.name, False, "malformed", f"missing required: {', '.join(missing)}"
                )
        return PrescreenVerdict(self.name, True, "clean")


class InferencePrescreen:
    """The LLM screen, as a dispatched Inference job (deep-dive §9).

    LLM-driven background work is an Inference job, not a subsystem of this sub-API, so
    this class is purely the adapter (`docs/PRINCIPLES.md` §1.3) — one seam, no Inference
    import at any other call site. With no dispatcher wired in it reports itself
    unavailable, which keeps contributions pending rather than waving them through.
    """

    name = "inference"

    def __init__(self, dispatcher: object | None = None) -> None:
        self._dispatcher = dispatcher

    async def prescreen(self, contribution: Contribution) -> PrescreenVerdict:
        if self._dispatcher is None:
            return PrescreenVerdict(
                self.name, False, "unavailable",
                "no Inference dispatcher is configured", available=False,
            )
        try:
            outcome = await self._dispatcher.prescreen_contribution(contribution)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - a screen failing is a verdict, never a crash
            return PrescreenVerdict(
                self.name, False, "unavailable", f"dispatch failed: {exc}", available=False
            )
        passed = bool(getattr(outcome, "passed", outcome))
        return PrescreenVerdict(
            self.name, passed, str(getattr(outcome, "verdict", "clean" if passed else "rejected")),
            str(getattr(outcome, "detail", "")),
        )


class PrescreenRegistry:
    """Runs every enabled provider. Any rejection is decisive; all-unavailable is not a pass."""

    def __init__(self, providers: tuple[PrescreenProvider, ...] | None = None) -> None:
        self._providers: dict[str, PrescreenProvider] = {
            p.name: p for p in (providers if providers is not None else (HeuristicPrescreen(),))
        }

    def register(self, provider: PrescreenProvider) -> None:
        self._providers[provider.name] = provider

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def run(self, contribution: Contribution) -> tuple[PrescreenVerdict, ...]:
        return tuple(
            [await self._providers[name].prescreen(contribution) for name in sorted(self._providers)]
        )


def combine_verdicts(verdicts: tuple[PrescreenVerdict, ...]) -> PrescreenVerdict:
    """Fold several providers' opinions into the one recorded on the contribution."""
    if not verdicts or all(not v.available for v in verdicts):
        return PrescreenVerdict("registry", False, "unavailable",
                                "no prescreen provider could form a verdict", available=False)
    rejections = [v for v in verdicts if v.available and not v.passed]
    if rejections:
        first = rejections[0]
        return PrescreenVerdict("registry", False, first.verdict,
                                f"{first.provider}: {first.detail}")
    return PrescreenVerdict("registry", True, "clean")


class ModerationQueue:
    """The queue itself: a plain table of contributions, deliberately not git.

    `_queue` is a genuinely mutable internal registry and therefore a plain dict; every
    value in it is a frozen `Contribution` replaced wholesale on each transition, so a
    contribution is never edited in place.
    """

    def __init__(
        self,
        entities: EntityManager,
        prescreen: PrescreenRegistry | None = None,
        mirror: ReviewAuditMirror | None = None,
    ) -> None:
        self._entities = entities
        self._prescreen = prescreen if prescreen is not None else PrescreenRegistry()
        # `is None`, never a truthiness test: `ReviewAuditMirror` defines `__len__`, so a
        # genuinely supplied but still-empty mirror is falsy and `or` would discard it —
        # silently detaching the caller's own audit trail from this queue.
        self._mirror = mirror if mirror is not None else ReviewAuditMirror()
        self._queue: dict[str, Contribution] = {}

    @property
    def mirror(self) -> ReviewAuditMirror:
        return self._mirror

    def submit(self, contribution: Contribution) -> ContributionResult:
        """Accept a contribution into the queue.

        The only way in. Nothing writes to `_queue` directly, which is what makes "a local
        fact never enters the queue on its own" (§3.1) checkable in one place.
        """
        self._queue[contribution.contribution_id] = contribution
        self._mirror.record_submission(contribution)
        return ContributionResult(contribution=contribution)

    async def prescreen(self, contribution_id: str) -> ContributionResult:
        contribution = self._queue.get(contribution_id)
        if contribution is None:
            return ContributionResult(
                error=_error(LearningErrorCode.UNKNOWN_CONTRIBUTION, contribution_id)
            )
        combined = combine_verdicts(await self._prescreen.run(contribution))
        if not combined.available:
            # `llm_prescreen_verdict` is deliberately left `None`: it is what
            # `Contribution.prescreened` reads, and `prescreened` is what `merge`'s own gate
            # checks. Recording the string "unavailable" here would make a contribution that
            # was never actually screened *look* screened, and the staff direct-to-global
            # path (`staff_review_status="not_applicable"`) would then clear every gate
            # `merge` has. An unavailable screen means review takes longer — it must not
            # leave a mark that satisfies the gate it failed to perform.
            self._mirror.record_prescreen(contribution, "unavailable")
            return ContributionResult(
                contribution=contribution,
                error=_error(LearningErrorCode.PRESCREEN_UNAVAILABLE, combined.detail),
            )
        updated = replace(contribution, llm_prescreen_verdict=combined.verdict)
        if not combined.passed:
            updated = replace(updated, staff_review_status="rejected")
        self._queue[contribution_id] = updated
        self._mirror.record_prescreen(updated, combined.verdict)
        return ContributionResult(contribution=updated)

    def review(
        self, contribution_id: str, reviewer: str, approved: bool, reason: str = ""
    ) -> ContributionResult:
        """A staff approve/reject on a user-shared contribution.

        Refuses a contribution on staff's own direct-to-global path: that one is marked
        `not_applicable` by design (§3.2), and letting a review land on it would blur the
        two paths into one.
        """
        contribution = self._queue.get(contribution_id)
        if contribution is None:
            return ContributionResult(
                error=_error(LearningErrorCode.UNKNOWN_CONTRIBUTION, contribution_id)
            )
        if contribution.staff_review_status == "not_applicable":
            return ContributionResult(
                contribution=contribution,
                error=_error(LearningErrorCode.STAFF_ROLE_REQUIRED,
                             "this contribution is on the staff direct-to-global path"),
            )
        if contribution.staff_review_status in ("approved", "rejected"):
            return ContributionResult(
                contribution=contribution, error=_error(LearningErrorCode.ALREADY_REVIEWED)
            )
        if not contribution.prescreened:
            return ContributionResult(
                contribution=contribution, error=_error(LearningErrorCode.PRESCREEN_REQUIRED)
            )
        decision = ReviewDecision(
            contribution_id=contribution_id, reviewer=reviewer, approved=approved, reason=reason
        )
        updated = replace(
            contribution, staff_review_status="approved" if approved else "rejected"
        )
        self._queue[contribution_id] = updated
        self._mirror.record_decision(decision)
        return ContributionResult(contribution=updated)

    def merge(self, contribution_id: str) -> ContributionResult:
        """Land an eligible contribution in the `GLOBAL` layer.

        The gates are checked here and nowhere else, in the order a caller would want to
        be told about them: unknown, already merged, not prescreened, not approved.
        """
        contribution = self._queue.get(contribution_id)
        if contribution is None:
            return ContributionResult(
                error=_error(LearningErrorCode.UNKNOWN_CONTRIBUTION, contribution_id)
            )
        if contribution.merged:
            return ContributionResult(
                contribution=contribution, error=_error(LearningErrorCode.ALREADY_MERGED)
            )
        if not contribution.prescreened:
            return ContributionResult(
                contribution=contribution, error=_error(LearningErrorCode.PRESCREEN_REQUIRED)
            )
        if contribution.staff_review_status not in ("approved", "not_applicable"):
            return ContributionResult(
                contribution=contribution, error=_error(LearningErrorCode.APPROVAL_REQUIRED)
            )
        if contribution.curation_type is not None:
            # A curation candidate's approval is the decision itself; the actual merge or
            # prune is Curate's own follow-up, staged as its own ordinary contribution.
            updated = replace(contribution, merged=True)
            self._queue[contribution_id] = updated
            self._mirror.record_merge(updated, contribution.target_entity_id or "")
            return ContributionResult(contribution=updated)

        applied = self._entities.apply_contribution(
            contribution.target_entity_type,
            contribution.target_entity_id,
            merge_payload(contribution),
        )
        if applied.error is not None or applied.entity is None:
            return ContributionResult(contribution=contribution, error=applied.error)
        updated = replace(contribution, merged=True)
        self._queue[contribution_id] = updated
        self._mirror.record_merge(updated, entity_id_of(applied.entity))
        return ContributionResult(contribution=updated)

    async def process(self, contribution_id: str) -> ContributionResult:
        """Prescreen, then merge if the contribution is already eligible.

        The staff direct-to-global path completes here; a user-shared one stops at
        `pending` and waits for `review`. One method for both, because the difference
        between the paths should be visible as data on the contribution, not as two
        separate call sequences a caller could get wrong.
        """
        screened = await self.prescreen(contribution_id)
        if screened.error is not None or screened.contribution is None:
            return screened
        if screened.contribution.staff_review_status in ("approved", "not_applicable"):
            return self.merge(contribution_id)
        return screened

    # ------------------------------------------------------------------------ reads

    def get(self, contribution_id: str) -> ContributionResult:
        found = self._queue.get(contribution_id)
        if found is None:
            return ContributionResult(
                error=_error(LearningErrorCode.UNKNOWN_CONTRIBUTION, contribution_id)
            )
        return ContributionResult(contribution=found)

    def all(self) -> tuple[Contribution, ...]:
        return tuple(self._queue.values())

    def pending(self) -> tuple[Contribution, ...]:
        return tuple(c for c in self._queue.values() if c.staff_review_status == "pending")

    def pending_longer_than(self, days: int) -> tuple[Contribution, ...]:
        cutoff = utcnow().timestamp() - days * 86400
        return tuple(c for c in self.pending() if c.submitted_at.timestamp() < cutoff)


__all__ = [
    "HeuristicPrescreen",
    "InferencePrescreen",
    "ModerationQueue",
    "PrescreenProvider",
    "PrescreenRegistry",
    "PrescreenVerdict",
    "combine_verdicts",
]
