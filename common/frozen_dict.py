"""The one centralized `FrozenDict` compatibility shim (`docs/PRINCIPLES.md` §2.1, §3.3).

There is deliberately exactly one of these in the repository. The Forward-Compatibility
Pattern's third point is "one centralized compatibility shim per capability, not scattered
version-conditional logic across call sites" — when the minimum supported Python is
eventually raised past 3.15, this file is the only thing that simplifies.

Two things about this that are easy to get wrong:

1. **Feature detection, not a version check.** `frozendict` is a builtin from Python 3.15
   (PEP 814), so it resolves as a bare name with no import. `NameError` is the signal that
   we are on an older interpreter and need the PyPI package. A `sys.version_info` check
   would be a hard-coded claim about a release that could still shift shape
   (`docs/PRINCIPLES.md` §3.3 point 2).

2. **The builtin is not a `dict` subclass.** It inherits directly from `object`, so
   `isinstance(x, dict)` silently returns False for it and any code gated on that check
   will quietly take the wrong branch. Use `isinstance(x, collections.abc.Mapping)`.

The matching install-time half of this lives in the dependency declaration as an
environment marker (`frozendict; python_version < '3.15'`) so the external package is
never installed on a newer interpreter rather than merely going unused. Validating that
this file actually takes the builtin branch on 3.15/3.16 — rather than silently continuing
to use the external package — is what `docs/PRINCIPLES.md` §3.3.1 asks for.
"""

from __future__ import annotations

try:
    FrozenDict = frozendict  # type: ignore[name-defined]  # Python 3.15+ builtin, PEP 814
except NameError:  # pragma: no cover - depends on interpreter version
    from frozendict import frozendict as FrozenDict  # type: ignore[no-redef]

__all__ = ["FrozenDict"]
