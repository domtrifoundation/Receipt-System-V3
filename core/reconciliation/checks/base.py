"""The `ReconciliationCheck` protocol and the check registry (§2, §4).

Every check in §4's inventory is a Provider Registry entry (`docs/PRINCIPLES.md` §1.2), and
**more than one runs at once** — §6's `RunChecksResponse` returns "one per check that ran",
which is only meaningful if running the inventory means running all of it. That is the shape a
check inventory needs anyway: a receipt with bad VAT math and a malformed TIN has two problems,
and a registry that stopped at the first hit would report one of them and hide the other until
it was fixed.

**A check that raises must not take down the sweep.** §4.4's degrade-gracefully rule applied
here means one broken check leaves the other ten reporting; `run_all` converts an escaped
exception into an `INCONCLUSIVE` result naming the check. The alternative — a sweep over ten
thousand old receipts aborting on one malformed row — is the failure that makes retroactive
checking unusable in practice, and `docs/PRINCIPLES.md` §1.9's promise is precisely that the
retroactive path works as well as the live one.

Checks are **async by signature even though §5 says most are pure-Python and fast**. Two of
them genuinely are not: §4.11's geo cross-reference is a real network call, and §4.10's archive
check reaches Disaster Recovery. A registry with two signatures would need every caller to know
which kind it held, and the uniform one costs a coroutine per fast check that was going to be
awaited in a batch anyway.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from common.frozen_dict import FrozenDict

from ..contracts import CheckOutcome, CheckResult, ReceiptSnapshot


@runtime_checkable
class ReconciliationCheck(Protocol):
    """§2's check protocol: a name, and a verdict about one receipt.

    `context` carries whatever collaborators a given check needs — Architect's vendor history,
    Disaster Recovery's blob checker, Geo/Address's providers. A mapping rather than a fixed
    argument list because the eleven checks need eleven different subsets of it, and widening
    every check's signature to the union would make each one's real dependencies unreadable.
    """

    @property
    def name(self) -> str: ...

    async def run(self, snapshot: ReceiptSnapshot, context: FrozenDict) -> CheckResult: ...


def passed(check_name: str, detail: str = "") -> CheckResult:
    """A clean result. Helper rather than a literal at forty call sites, so "passed" has one
    shape and a reviewer can grep for the ones that are not it."""
    return CheckResult(check_name=check_name, outcome=CheckOutcome.PASSED, detail=detail)


def inconclusive(check_name: str, detail: str) -> CheckResult:
    """A check that could not reach a verdict.

    Requires a `detail` — an inconclusive result with no reason is indistinguishable from a
    check that silently does nothing, and §4.12's whole point is that "could not check" is real
    information rather than an absence of it.
    """
    return CheckResult(check_name=check_name, outcome=CheckOutcome.INCONCLUSIVE, detail=detail)


def flagged(
    check_name: str,
    flag_type: str,
    severity,
    detail: str,
    evidence: FrozenDict | None = None,
) -> CheckResult:
    """A hit. `evidence` is a `FrozenDict` (§2.1) so the payload handed to Review/Flagging
    cannot be edited by whichever consumer reads it on the way to a human."""
    return CheckResult(
        check_name=check_name,
        outcome=CheckOutcome.FLAGGED,
        flag_type=flag_type,
        severity=severity,
        detail=detail,
        evidence=evidence if evidence is not None else FrozenDict({}),
    )


class CheckRegistry:
    """§1.2's Provider Registry for the check inventory.

    Registration is by the check's own `name`, and a duplicate name is rejected rather than
    silently overwriting: two checks answering to one name means one of them stops running and
    nothing anywhere reports that it did.
    """

    def __init__(self) -> None:
        self._checks: dict[str, ReconciliationCheck] = {}

    def register(self, check: ReconciliationCheck) -> None:
        if check.name in self._checks:
            raise ValueError(f"a check named {check.name!r} is already registered")
        self._checks[check.name] = check

    def get(self, name: str) -> ReconciliationCheck | None:
        return self._checks.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._checks)

    def __len__(self) -> int:
        return len(self._checks)

    async def run_all(
        self, snapshot: ReceiptSnapshot, context: FrozenDict | None = None
    ) -> tuple[CheckResult, ...]:
        """Run every registered check against one receipt and return all their verdicts.

        Sequential rather than gathered. Most checks are pure-Python over already-fetched data
        (§5), so concurrency buys nothing for nine of the eleven, and the two that do I/O are
        budget-gated per §5 rather than fired unconditionally — gathering would defeat that gate
        by launching every geo lookup in a sweep at once.
        """
        ctx = context if context is not None else FrozenDict({})
        results: list[CheckResult] = []
        for name, check in self._checks.items():
            try:
                results.append(await check.run(snapshot, ctx))
            except Exception as exc:  # noqa: BLE001 - see this module's docstring
                results.append(
                    inconclusive(name, f"check raised {type(exc).__name__}: {exc}")
                )
        return tuple(results)


__all__ = [
    "CheckRegistry",
    "ReconciliationCheck",
    "flagged",
    "inconclusive",
    "passed",
]
