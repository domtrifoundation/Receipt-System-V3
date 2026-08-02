"""Setup API's data contracts — types only, no logic (`docs/PRINCIPLES.md` §1.1).

**Partially implemented, stated so the gap is not mistaken for a finished file.** The Setup API
deep-dive's §3 also specifies `HardwareProfile`, `GpuInfo` and `WizardState` here; those arrive
with hardware detection (§5) and the wizard (§7), neither of which is implemented yet. What is
here is the per-service venv provisioning surface (`docs/VENV_AND_IMPORTS.md`) — the mechanism
behind the "dependency installation" this API's own §1 has always claimed to own but never
described.

Provisioning failures are **data**, not exceptions (`docs/PRINCIPLES.md` §4.1). A clone with one
unprovisionable service has to report *which* service and *why*, and has to keep going and
report on the rest rather than aborting at the first bad one — an operator needs the whole
picture to decide whether the clone is salvageable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = [
    "ProvisionError",
    "ProvisionErrorCode",
    "ProvisionOutcome",
    "ProvisionReport",
    "ServiceVenvSpec",
]


class ProvisionErrorCode(str, Enum):
    """Why one service's venv could not be provisioned.

    Distinct codes rather than one generic failure, because the operator action differs
    completely: a missing/unusable interpreter is an environment problem, a dependency
    resolution failure is usually platform wheel availability, and a missing source directory
    means the clone itself is malformed and should not be cut over to at all.
    """

    VENV_CREATION_FAILED = "venv_creation_failed"
    DEPENDENCY_INSTALL_FAILED = "dependency_install_failed"
    SOURCE_DIR_MISSING = "source_dir_missing"
    INTERPRETER_UNUSABLE = "interpreter_unusable"


@dataclass(frozen=True)
class ProvisionError:
    code: ProvisionErrorCode

    detail: str
    """The real failure text — pip's or venv's own stderr, not a summarised paraphrase.

    `v3-plan-04-v2-audit-findings.md` records V2 discarding tracebacks in favour of `str(e)` as
    a concrete cause of hard debugging; the same lesson applies to a subprocess's stderr. A
    bare "install failed" tells an operator nothing they can act on.
    """


@dataclass(frozen=True)
class ServiceVenvSpec:
    """One service's venv, fully resolved against one specific clone.

    Produced by discovery rather than a hardcoded service list, so a newly added Core API is
    picked up the day it lands. The corpus's single most-repeated structural mistake is a new
    API never being wired into the cross-cutting machinery that enumerates all of them
    (`v3-plan-03-decisions.md`'s own root-cause note on that pattern) — a hardcoded list here
    would be one more place to forget.
    """

    import_path: str
    """Dotted path, e.g. `core.ocr` — and also the venv directory's own name.

    Deliberately not the bare leaf name: `core/` and `services/` are separate trees that can
    hold the same leaf (`execution_core` is in both today), so a bare name is genuinely
    ambiguous (`docs/VENV_AND_IMPORTS.md` §2).
    """

    source_dir: Path
    venv_dir: Path

    requirement_files: tuple[Path, ...]
    """Ordered: the shared base first, then this service's own if it has one.

    Ordered and a tuple rather than a set because this is an install *sequence* — pip resolves
    later requirements against what earlier ones already pinned.
    """


@dataclass(frozen=True)
class ProvisionOutcome:
    import_path: str
    venv_dir: Path

    created: bool
    """False when the venv already existed and was left alone.

    Provisioning is idempotent and safely re-runnable — the same property Setup's own bootstrap
    has, and for the same reason (`v3-deepdive-11-setup-api.md` §4): re-running after a partial
    failure must be a normal, safe operation, not a reason to start over.
    """

    error: ProvisionError | None = None


@dataclass(frozen=True)
class ProvisionReport:
    outcomes: tuple[ProvisionOutcome, ...]

    @property
    def failed(self) -> tuple[ProvisionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.error is not None)

    @property
    def fully_provisioned(self) -> bool:
        """Whether this clone is eligible for cutover at all.

        A clone with any service unprovisioned must never be cut over to: a service whose venv
        is half-built is not a degraded service, it is an import error at launch. Supervisor
        keeps serving the prior release instead, which is its existing rollback path rather than
        a new mechanism (`docs/VENV_AND_IMPORTS.md` §5).
        """
        return not self.failed
