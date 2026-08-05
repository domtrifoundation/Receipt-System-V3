"""Resolving a running service's own install root from its own file location.

Every service launched by Supervisor's Boot Sequence (`supervisor/boot_sequence.py`)
runs with `cwd` set to its own release clone (`<install_root>/releases/<version>_<hash>/`),
not the install root itself — so a servicer that needs to read or write its own small
persisted config file (the same `<install_root>/<api>/*.json` pattern `supervisor/
arbitration.py`'s `ChannelArbitrator` and `supervisor/version_pins.py`'s `VersionPinStore`
already use) has no argument or environment variable telling it where that install root
is. This was a real, previously-unfilled gap: no service threaded `install_root` at all
before this, because there was never a shared, honest way to compute it.

Same technique as `common/version.py`'s own `resolve_commit_hash()`: walk up from the
calling module's own file path looking for the one directory name Update API's own
`release_manager.py` always uses (`releases/<version>_<hash>/`) — if a `releases`-named
parent is found, its own parent is the install root. Degrades to `None` in a dev checkout
(this repo cloned directly, never inside a `releases/` directory), which callers must
treat as "unknown," never as an error (`docs/PRINCIPLES.md` §4.4) — the identical posture
`resolve_commit_hash()` already takes for the same reason.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["resolve_install_root"]


def resolve_install_root(module_path: Path | None = None) -> Path | None:
    """`module_path` defaults to the caller's own `__file__`-derived location is the
    caller's job to pass — this function takes no `__file__` magic of its own so it stays
    trivially testable with a synthetic path."""
    here = (module_path or Path(__file__)).resolve()
    for parent in here.parents:
        if parent.name == "releases":
            return parent.parent
    return None
