"""A small, pure-Python 5-field cron-expression parser and next-occurrence calculator.

**Not in the deep-dive's §2 package layout, and not `croniter`.** §8 names `croniter` (or an
equivalent pure-Python cron parser) as "the only real addition" this sub-API needs — but this
build may not add a new third-party dependency (see this package's `CLAUDE.md`), so this
module is that equivalent, written from scratch rather than left unimplemented. It sits behind
its own small interface (`parse()`, `next_after()`) for the identical reason `docs/PRINCIPLES.md`
§1.3 asks any external dependency to sit behind one small adapter: the day `croniter` is
actually added to `requirements.txt`, this file is the only thing that changes, and nothing
that calls `next_after()` needs to know or care.

**Scope, deliberately**: standard 5-field cron (`minute hour day-of-month month day-of-week`),
supporting `*`, a single value, a comma-separated list, a range (`a-b`), and a step (`*/n` or
`a-b/n`) per field — enough to express every example the deep-dive itself gives ("every Sunday
at 2am" = `0 2 * * 0`; "every quarter" = `0 0 1 1,4,7,10 *`). Named schedules (`@daily`) and
the classic day-of-month/day-of-week OR-quirk some cron implementations apply are both out of
scope — neither is needed for anything this sub-API's own deep-dive names, and a smaller,
fully-understood parser is worth more here than a partial reimplementation of every historical
cron dialect's own edge case.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .errors import InvalidCronExpression

_FIELD_RANGES = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 6),  # 0 = Sunday, matching the deep-dive's own "0" for Sunday
)

#: A next-occurrence search stops after this many days rather than looping forever on an
#: expression that can never actually match (a day-of-month field pinned past what every
#: month in the search window has, given this parser's own scope does not resolve the
#: day-of-month/day-of-week OR-quirk).
_MAX_SEARCH_DAYS = 366 * 5


def _parse_field(raw: str, low: int, high: int, field_name: str) -> frozenset[int]:
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise InvalidCronExpression(f"{field_name}: empty term in {raw!r}")
        step = 1
        if "/" in part:
            base, _, step_raw = part.partition("/")
            try:
                step = int(step_raw)
            except ValueError as exc:
                raise InvalidCronExpression(
                    f"{field_name}: bad step {step_raw!r} in {raw!r}"
                ) from exc
            if step <= 0:
                raise InvalidCronExpression(f"{field_name}: step must be positive in {raw!r}")
        else:
            base = part
        if base == "*":
            start, end = low, high
        elif "-" in base:
            lo_raw, _, hi_raw = base.partition("-")
            try:
                start, end = int(lo_raw), int(hi_raw)
            except ValueError as exc:
                raise InvalidCronExpression(
                    f"{field_name}: bad range {base!r} in {raw!r}"
                ) from exc
            if start > end:
                raise InvalidCronExpression(f"{field_name}: reversed range {base!r} in {raw!r}")
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise InvalidCronExpression(
                    f"{field_name}: not a number {base!r} in {raw!r}"
                ) from exc
        if start < low or end > high:
            raise InvalidCronExpression(
                f"{field_name}: {base!r} out of range {low}-{high} in {raw!r}"
            )
        values.update(range(start, end + 1, step))
    if not values:
        raise InvalidCronExpression(f"{field_name}: no values resolved from {raw!r}")
    return frozenset(values)


class ParsedCron:
    """The five parsed field sets. Immutable and reusable across many `next_after()` calls —
    a caller checking many tasks against the current moment parses each expression once."""

    __slots__ = ("minute", "hour", "day", "month", "weekday", "expression")

    def __init__(self, expression: str, fields: tuple[frozenset[int], ...]) -> None:
        self.expression = expression
        self.minute, self.hour, self.day, self.month, self.weekday = fields

    def matches(self, moment: datetime) -> bool:
        return (
            moment.minute in self.minute
            and moment.hour in self.hour
            and moment.day in self.day
            and moment.month in self.month
            and (moment.isoweekday() % 7) in self.weekday  # Python: Mon=1..Sun=7 -> Sun=0
        )

    def matches_date(self, day: date) -> bool:
        """The three date-shaped fields only — used to skip whole non-matching days without
        checking all 1440 minutes in each of them."""
        return (
            day.day in self.day
            and day.month in self.month
            and (day.isoweekday() % 7) in self.weekday
        )


def parse(expression: str) -> ParsedCron:
    """Parse a 5-field cron expression, or raise `InvalidCronExpression`.

    Raising here (rather than returning error data) is deliberate and scoped: this is an
    internal helper, not this API's own boundary — `errors.py`'s docstring is explicit that
    every *boundary* call converts this into `error_code`/`error_detail` before it is ever
    handed back to a caller (`docs/PRINCIPLES.md` §4.1). `registry.py` and `store.py` are
    exactly where that conversion happens.
    """
    parts = expression.split()
    if len(parts) != 5:
        raise InvalidCronExpression(
            f"expected 5 fields (minute hour day month weekday), got {len(parts)} in "
            f"{expression!r}"
        )
    fields = tuple(
        _parse_field(part, low, high, name)
        for part, (name, low, high) in zip(parts, _FIELD_RANGES)
    )
    return ParsedCron(expression, fields)


def next_after(expression: str, after: datetime) -> datetime:
    """The first occurrence of `expression` strictly after `after`, minute resolution.

    Two-level search rather than a flat minute-by-minute scan over the whole bound: cron's
    own real granularity is the minute, but almost every day in the search window is not a
    candidate at all once day-of-month/month/weekday are considered, so this checks whole
    days first (`ParsedCron.matches_date`) and only walks all 1440 minutes of a day that
    actually matches. Bounded by `_MAX_SEARCH_DAYS` so a pathological expression fails loudly
    rather than spinning forever; reaching that bound with any expression this parser's own
    scope actually admits would itself be a bug worth seeing immediately rather than a hang.
    """
    parsed = parse(expression)
    start = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    day = start.date()
    last_day = (after + timedelta(days=_MAX_SEARCH_DAYS)).date()
    while day <= last_day:
        if parsed.matches_date(day):
            if day == start.date():
                candidate = start
                minutes_today = 1440 - (start.hour * 60 + start.minute)
            else:
                candidate = datetime.combine(day, time.min, tzinfo=start.tzinfo)
                minutes_today = 1440
            for _ in range(minutes_today):
                if parsed.matches(candidate):
                    return candidate
                candidate += timedelta(minutes=1)
        day += timedelta(days=1)
    raise InvalidCronExpression(
        f"{expression!r} has no occurrence within {_MAX_SEARCH_DAYS} days of {after.isoformat()}"
    )


__all__ = ["ParsedCron", "next_after", "parse"]
