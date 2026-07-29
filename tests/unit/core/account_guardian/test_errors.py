"""`errors.py` — the internal exception hierarchy and the wire-code lookup, in
`core/logs/errors.py`'s own shape (the task's explicit reference)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.account_guardian.errors import (
    ERROR_SUMMARIES,
    AccountGuardianError,
    CapabilityMissing,
    DependencyUnavailable,
    NotFound,
    OwnershipDenied,
    code_for,
)


def test_every_declared_exception_has_a_summary():
    """A code with no summary is a code a client can show but this API cannot explain."""
    for exc_cls in (AccountGuardianError, OwnershipDenied, NotFound, CapabilityMissing, DependencyUnavailable):
        assert exc_cls.code in ERROR_SUMMARIES, f"{exc_cls.__name__}.code has no summary"


def test_code_for_returns_the_exceptions_own_code():
    assert code_for(OwnershipDenied("x")) == "OWNERSHIP_DENIED"
    assert code_for(NotFound("x")) == "NOT_FOUND"


def test_code_for_an_unmapped_exception_degrades_to_write_failed():
    """Unmapped is deliberately not a crash of its own — a caller receiving `WRITE_FAILED`
    with a real detail string is strictly better off than one receiving a crash from the
    error path itself (mirrors `core/logs/errors.py.code_for`'s own reasoning)."""
    assert code_for(ValueError("something else entirely")) == "WRITE_FAILED"


@pytest.mark.forward_compat
def test_error_summaries_is_a_frozen_dict_not_a_plain_dict():
    assert isinstance(ERROR_SUMMARIES, Mapping)
    assert isinstance(ERROR_SUMMARIES, FrozenDict)
    with pytest.raises(Exception):
        ERROR_SUMMARIES["NEW_CODE"] = "should not be settable"  # type: ignore[index]
