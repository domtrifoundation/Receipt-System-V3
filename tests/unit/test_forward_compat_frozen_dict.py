"""Forward-Compatibility Pattern validation for `common/frozen_dict.py`.

This is the concrete gap `docs/PRINCIPLES.md` §3.3.1 names directly: the environment-marker
install (`frozendict; python_version < '3.15'`) stops the external package from being
*installed* on a newer interpreter, but that alone doesn't prove the shim's code path
actually *uses* the real built-in once it's available — it could still silently succeed by
falling through to some other branch. These tests check the resolved type itself, on
whichever interpreter they happen to run under, so `nox -s forward_compat` (noxfile.py)
running this under both 3.14 and 3.15 is what turns "should resolve to the builtin" into
"confirmed it did."

Every assertion below was checked empirically against a real 3.14 and a real 3.15.0b4
interpreter before being written — not assumed from the PEP text. One result was genuinely
worth confirming rather than guessing: the *external* PyPI `frozendict` package **is** a
`dict` subclass (`type(d).__module__ == "frozendict"`, `isinstance(d, dict) is True`), while
the Python 3.15 **builtin** is not (`type(d).__module__ == "builtins"`,
`isinstance(d, dict) is False`). The shim's own docstring only ever claimed the builtin
isn't a `dict` subclass — this file is what confirms that claim against a real interpreter
instead of leaving it as an assertion nobody checked.
"""

from __future__ import annotations

import collections.abc
import sys

import pytest

from common.frozen_dict import FrozenDict


def test_frozen_dict_is_always_a_mapping():
    """True on every supported interpreter — the one invariant callers should rely on.

    `docs/PRINCIPLES.md` §2.1 says to prefer `isinstance(x, collections.abc.Mapping)` over
    `isinstance(x, dict)` precisely because the latter isn't version-stable (see the two
    tests below). This test is the version-independent half of that guidance: the Mapping
    check must hold regardless of which branch the shim took.
    """
    d = FrozenDict({"a": 1})
    assert isinstance(d, collections.abc.Mapping)
    assert d["a"] == 1


def test_frozen_dict_rejects_mutation():
    """Both the builtin and the PyPI package are genuinely immutable — not just typed as
    frozen while still allowing item assignment underneath."""
    d = FrozenDict({"a": 1})
    with pytest.raises(TypeError):
        d["a"] = 2  # type: ignore[index]


@pytest.mark.forward_compat
def test_resolves_to_the_real_builtin_on_3_15_plus():
    """The actual §3.3.1 requirement: on 3.15+, this must be `builtins.frozendict`, not the
    external package silently still imported and used underneath the same name."""
    if sys.version_info < (3, 15):
        pytest.skip("builtin frozendict (PEP 814) does not exist before 3.15")

    assert FrozenDict.__module__ == "builtins", (
        f"expected the Python 3.15+ builtin frozendict, but common.frozen_dict.FrozenDict "
        f"resolved to {FrozenDict.__module__}.{FrozenDict.__qualname__} instead — the shim "
        f"is silently still using the external PyPI package on an interpreter that ships "
        f"the real thing."
    )
    d = FrozenDict({"a": 1})
    assert not isinstance(d, dict), (
        "the Python 3.15+ builtin frozendict is not a dict subclass; if this is failing, "
        "FrozenDict resolved to something else entirely (see the module check above)"
    )


@pytest.mark.forward_compat
def test_resolves_to_the_pypi_package_before_3_15():
    """The complementary check: on a pre-3.15 interpreter, the environment-marker install
    means the external package must be what's actually in use, not some other fallback."""
    if sys.version_info >= (3, 15):
        pytest.skip("this interpreter has the real builtin; see the sibling test")

    assert FrozenDict.__module__ == "frozendict", (
        f"expected the PyPI frozendict package pre-3.15, but common.frozen_dict.FrozenDict "
        f"resolved to {FrozenDict.__module__}.{FrozenDict.__qualname__} instead"
    )
    # Recorded here because it's genuinely easy to get backwards from reading the PEP alone:
    # the *external* package IS a dict subclass, unlike the builtin it's standing in for.
    # A caller relying on isinstance(x, dict) would see different behavior across this
    # exact version boundary — which is the whole reason §2.1 prefers Mapping instead.
    d = FrozenDict({"a": 1})
    assert isinstance(d, dict)
