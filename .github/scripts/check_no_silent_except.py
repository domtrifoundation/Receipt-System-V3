#!/usr/bin/env python3
"""Fail if any newly-added `except` block swallows an error without logging it.

## Why this check exists

A real, live-confirmed gap, not a hypothetical one: `core/logs/writer.py`'s `LogWriter`
(unconditional full-traceback capture, verbosity gating, non-blocking appends — real,
independently tested) had **zero callers anywhere outside `core/logs/` itself**,
confirmed by grepping the entire repository. Every `except Exception: pass`-shaped
best-effort catch in every other package genuinely wrote to nothing. `core/ingestion/
service.py`'s own four such catches were the first ones actually fixed and are the model
this check enforces going forward: an `except` that doesn't re-raise must call something
that looks like a real log write (a method call with "log" in its name, e.g.
`self._log_writer.log_exception(...)`), not just `pass`/`continue`/a bare comment.

## What it checks

Walks every `.py` file under the source roots, parses it with `ast`, and inspects every
**broad** `except` handler — bare `except:`, `except Exception:`, or `except
BaseException:` (and tuples containing one of those). A narrow, named exception type
(`except SourceUnavailable:`, `except KeyError:`) converted into a clean error-as-data
return is this project's own correct, intentional pattern (`docs/PRINCIPLES.md` §4.1) —
not the failure mode this check exists to catch, and logging every one of those would be
noise, not signal. A broad handler is a **violation** unless at least one of these is true:

- the handler body contains a `raise` (re-raising is not swallowing)
- the handler body contains a call whose function name contains `log` (case-insensitive)
  anywhere in the call chain (`self._log_writer.log_exception(...)`, `logger.error(...)`,
  `logging.exception(...)`, etc.)
- the line is listed in the checked-in baseline (`.github/silent_except_baseline.json`) --
  grandfathered pre-existing debt, visible but not blocking

## The baseline, and why it exists

This repository had a large amount of this exact pattern before this check was written --
failing every one of those in one shot would block unrelated PRs on a cleanup this check's
own introduction should not demand up front. `.github/silent_except_baseline.json` is a
real, generated snapshot of every violation that existed the day this check was added.
**A new violation not in the baseline fails CI.** The baseline only ever shrinks (as
existing sites get fixed and their entries stop matching, `--update-baseline` removes
them) -- it must never grow to grandfather something new.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / ".github" / "silent_except_baseline.json"

SOURCE_ROOTS = ("core", "services", "supervisor", "common")

#: Directory names to skip anywhere under a source root.
SKIP_DIR_NAMES = frozenset({"__pycache__", "generated", "node_modules", ".venv", "venv"})

#: File name patterns that are test code, not production code -- a test's own `except` in
#: an assertion helper is a different, lower-stakes question than production error
#: handling, and this check is about the latter.
SKIP_FILE_PREFIXES = ("test_",)


def _iter_source_files():
    for root_name in SOURCE_ROOTS:
        root = REPO_ROOT / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.name.startswith(SKIP_FILE_PREFIXES):
                continue
            yield path


def _call_name(node: ast.Call) -> str:
    """Best-effort dotted name for a call's own function, e.g. `self._log_writer.log_exception`."""
    parts: list[str] = []
    target = node.func
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return ".".join(reversed(parts))


#: Names that make a handler "broad" -- catches errors the author did not specifically
#: anticipate, which is exactly the class this check is about. A handler naming only
#: specific, narrow exception types (however many) is deliberately never flagged.
_BROAD_EXCEPTION_NAMES = frozenset({"Exception", "BaseException"})


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:  # bare `except:`
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for t in types:
        name = t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", None)
        if name in _BROAD_EXCEPTION_NAMES:
            return True
    return False


def _handler_logs(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call) and "log" in _call_name(node).lower():
            return True
    return False


def find_violations() -> list[str]:
    """Returns `"relative/path.py:123"` for every unlogged, non-re-raising, *broad* `except`."""
    violations: list[str] = []
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_broad(node) and not _handler_logs(node):
                rel = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel}:{node.lineno}")
    return sorted(violations)


def _load_baseline() -> set[str]:
    if not BASELINE_PATH.is_file():
        return set()
    return set(json.loads(BASELINE_PATH.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-baseline", action="store_true", help="Write the current violation set as the new baseline.")
    args = parser.parse_args()

    violations = find_violations()

    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(violations, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(violations)} baseline entries to {BASELINE_PATH}.")
        return 0

    baseline = _load_baseline()
    new_violations = [v for v in violations if v not in baseline]
    fixed = sorted(baseline - set(violations))

    if fixed:
        print(f"{len(fixed)} baseline entr{'y' if len(fixed) == 1 else 'ies'} no longer reproduce "
              f"(fixed, or the code moved) -- run with --update-baseline to shrink the baseline:")
        for entry in fixed:
            print(f"  - {entry}")

    if new_violations:
        print(f"::error::{len(new_violations)} new silent `except` block(s) found -- an except that "
              "doesn't re-raise must call something with 'log' in its name (e.g. a real "
              "LogWriter.log_exception call), not just pass/continue. See "
              ".github/scripts/check_no_silent_except.py's own docstring for the full rule.")
        for entry in new_violations:
            print(f"  NEW: {entry}")
        return 1

    print(f"No new silent except blocks ({len(violations)} total, all in baseline).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
