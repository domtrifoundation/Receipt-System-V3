"""No tool is registered here, and that is this deep-dive's own resolved conclusion, not
an unfinished scaffold (`v3-deepdive-07-tool-call-api.md` §9): "Whether any settings-
change tool is needed during automated processing at all, resolved: no, not in the
initial design. Automated processing is about receipt reconciliation, not settings
management — a genuinely different concern with no clear need to blend into the same
tool-calling context. Settings changes stay a human/staff UI action exclusively unless a
concrete, specific need surfaces later; not built speculatively now."

§4.2 sketches what such a tool *would* look like if one were ever needed — `MUTATING_
STAGED`, staging a proposed change into a review queue the same shape Architect already
uses for vendor contributions — so a future session adding one has a real design to build
against rather than starting from nothing. Building it now, with no concrete caller, would
be exactly the kind of speculative scope this project's own §1.8/§3.4 discipline argues
against elsewhere (Task Scheduler's allowlist starting empty until a real action is
registered is the identical posture).

`register_settings_tools` exists as a real, callable no-op — matching `core/migration/
steps/`'s own deliberately-empty registration point — so `service.py`'s assembly can call
it unconditionally without a special case, and the moment a real settings-change tool is
designed, this is where it registers.
"""

from __future__ import annotations

from ..registry import ToolRegistry

__all__ = ["register_settings_tools"]


def register_settings_tools(registry: ToolRegistry) -> None:
    """Deliberately empty — see the module docstring. Not a placeholder forgotten mid-
    implementation; a decision already made and recorded."""
    return
