"""Contract-shape tests for Logs API.

The load-bearing one here is `LEVEL_STYLE_HINT`: `docs/PRINCIPLES.md` §2.1.1 was written from
this exact module as one of its two motivating instances, so "it is a `FrozenDict`, and code
checking it tests `Mapping` rather than `dict`" is a property worth asserting rather than
assuming from a type annotation nothing enforces at runtime.
"""

from __future__ import annotations

import collections.abc
from datetime import datetime, timezone

import pytest

from common.frozen_dict import FrozenDict
from core.logs.contracts import (
    LEVEL_SEVERITY,
    LEVEL_STYLE_HINT,
    LogEntry,
    LogLevel,
    RetentionPolicy,
    Verbosity,
    utcnow,
)


def _entry(**over) -> LogEntry:
    base = dict(
        timestamp=datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc),
        run_id="run-1",
        user_id="user-1",
        service="ocr",
        level=LogLevel.INFO,
        message="engine finished",
    )
    base.update(over)
    return LogEntry(**base)


def test_level_style_hint_covers_every_level():
    """A level with no hint would force a client to invent one — the exact drift §3.4 says
    the hint exists to prevent."""
    assert set(LEVEL_STYLE_HINT) == set(LogLevel)
    assert set(LEVEL_SEVERITY) == set(LogLevel)


def test_attention_is_not_a_renamed_warning():
    """§3.4: `ATTENTION` outranks `ERROR` and carries a deliberately distinct hint, so a
    client can give it real visual priority rather than letting it blend into an
    ERROR-coloured stream."""
    assert LEVEL_SEVERITY[LogLevel.ATTENTION] > LEVEL_SEVERITY[LogLevel.ERROR]
    assert LEVEL_STYLE_HINT[LogLevel.ATTENTION] != LEVEL_STYLE_HINT[LogLevel.ERROR]
    assert LEVEL_STYLE_HINT[LogLevel.ATTENTION] == "critical_persistent"


def test_level_style_hint_is_immutable():
    """The failure this prevents is a single accidental in-place mutation somewhere, which
    every later reader then sees and nobody can trace back."""
    with pytest.raises(TypeError):
        LEVEL_STYLE_HINT[LogLevel.INFO] = "loud"  # type: ignore[index]


@pytest.mark.forward_compat
def test_level_style_hint_is_a_mapping_not_necessarily_a_dict():
    """The §2.1.1 gotcha, asserted on whichever interpreter this runs under.

    On 3.15+ `FrozenDict` is the builtin, which is **not** a `dict` subclass — so any
    `isinstance(..., dict)` guard against this table silently takes the wrong branch. The
    invariant callers may rely on is `Mapping`, and that must hold on every interpreter.
    """
    assert isinstance(LEVEL_STYLE_HINT, collections.abc.Mapping)
    assert isinstance(LEVEL_STYLE_HINT, type(FrozenDict({})))


def test_log_entry_is_frozen_and_holds_a_frozen_context():
    entry = _entry(context=FrozenDict({"engine": "paddle", "ms": 812}))
    with pytest.raises(Exception):
        entry.message = "changed"  # type: ignore[misc]
    assert isinstance(entry.context, collections.abc.Mapping)
    with pytest.raises(TypeError):
        entry.context["engine"] = "rapid"  # type: ignore[index]


def test_entry_publishes_its_own_style_hint():
    """Owned where the level is defined, not re-derived by whoever renders it."""
    assert _entry(level=LogLevel.ATTENTION).suggested_style == "critical_persistent"


def test_verbosity_per_service_override():
    """§8: OCR and Inference default to trace because their raw output is the high-volume
    thing being debugged — without dragging every other service's tier down with them."""
    v = Verbosity()
    assert v.level_for("ocr") is LogLevel.TRACE
    assert v.level_for("inference") is LogLevel.TRACE
    assert v.level_for("preprocessing") is LogLevel.INFO
    assert isinstance(v.per_service, collections.abc.Mapping)


def test_retention_defaults_match_the_resolved_open_questions():
    """§10 locked both of these in; a silent change to either is a policy change."""
    policy = RetentionPolicy()
    assert policy.retention_days == 90
    assert policy.trace_retention_days == 7


def test_utcnow_is_timezone_aware():
    assert utcnow().tzinfo is not None
