"""The worked example a real migration step follows (§2, §3, §8).

**This is not a shipped step and is not registered by `register_all`.** Every structure kind is
at version 1 today, so there is no bump to perform. It exists because §2's package layout names
`v1_to_v2.py` explicitly and §3 makes "one file per version bump" a deliberate constraint — and
the moment someone genuinely needs to write the first migration, they will be doing it under
release pressure against a real user's database. Having the shape already written down, with
the idempotency contract spelled out, is worth more then than a blank folder.

**The one thing a step author must get right** is the return value. Returning `True` means "I
did real work"; returning `False` means "this structure already carried the change". §8's
idempotency hook rests entirely on that distinction being honest, because the runner cannot
determine it — only the step knows what change to look for. A step that always returned `True`
would make an interrupted batch's re-run report a full migration it never performed.

**A step does not manage its own transaction.** §1 is explicit: migrations write through
Persistence's normal path, so each one is already atomic and Historian-logged, and this API
owns no rollback machinery. A step that opened its own transaction would be building the
second mechanism §1 says is unnecessary.
"""

from __future__ import annotations

from ..contracts import MigrationStep, StructureKind

#: What this step would describe, if it were real. A module constant so a test can register it
#: without restating the metadata, and so the example is a complete one.
STEP = MigrationStep(
    kind=StructureKind.DATABASE_SCHEMA,
    from_version=1,
    to_version=2,
    description="Example only — the shape a real N->N+1 step takes. Not registered.",
)


async def apply(structure_id: str) -> bool:
    """Bump one structure from 1 to 2, returning whether real work was done.

    A real implementation reads the structure through Persistence, checks whether the change is
    already present, applies it through Persistence's normal write path if not, and returns
    accordingly. The check-first shape is not an optimisation — it is the whole of the
    idempotency guarantee, and writing it as an unconditional apply is the mistake §8 exists to
    catch.

    This example performs nothing and reports that it performed nothing, which is the honest
    answer for a step that is not real.
    """
    return False


__all__ = ["STEP", "apply"]
