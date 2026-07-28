#!/usr/bin/env python3
"""Fail if any source package directory is matched by a `.gitignore` rule.

## Why this check exists

It exists because of a real, already-happened bug, not a hypothetical one.

`.gitignore` carried an unanchored `logs/` rule, intended for the rotated flat files
Logs API writes at runtime (`v3-plan-01-core-apis.md` #13). An unanchored directory
pattern in gitignore matches at *any* depth, so it also matched `core/logs/` — the Logs
API's own **source package**. The consequence was silent and expensive: Phase 1's
scaffolding pass created 31 of the 32 Core API packages, `git add` obediently ignored the
32nd, every CI check passed, and the Logs API had no package at all for an entire
development phase before anyone noticed.

Nothing in the toolchain reported it, and nothing would have. `git add` ignoring a path it
was told to ignore is not an error; a missing directory is not a diff. That is precisely
the shape of failure worth a cheap, permanent guard.

## What it checks

Every directory under the source roots below is tested against the repository's own ignore
rules via `git check-ignore`. Any hit is a failure. This is deliberately a *structural*
check on the ignore rules rather than a list of expected packages — a hardcoded roster of
"the 32 Core APIs" would itself go stale the next time an API is added, which is the exact
class of drift `docs/PRINCIPLES.md` and this project's own history keep correcting.

The check is about **source directories only**. Ignoring build output, caches, venvs, and
real user data is correct and stays untouched — every one of those lives outside the roots
below.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Directories that hold this project's own source. Anything under one of these is code
#: that must be committable. `webapp/` is included but its own build output (`dist/`,
#: `.vite/`, `node_modules/`) is legitimately ignored, so those are skipped explicitly.
SOURCE_ROOTS = ("core", "services", "supervisor", "common", "webapp", "tests")

#: Directory names that are legitimately ignored even inside a source root — build output
#: and caches, never source. Matched on the directory's own name at any depth.
LEGITIMATELY_IGNORED = frozenset(
    {
        "__pycache__",
        "node_modules",
        "dist",
        ".vite",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "real_receipts",
        "real_receipt_fixtures",
    }
)


def source_directories(repo: Path) -> list[Path]:
    """Every directory under a source root, excluding the legitimately-ignored names."""
    found: list[Path] = []
    for root in SOURCE_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        found.append(base)
        for path in base.rglob("*"):
            if not path.is_dir():
                continue
            if LEGITIMATELY_IGNORED & set(path.relative_to(repo).parts):
                continue
            found.append(path)
    return found


def ignored_paths(repo: Path, paths: list[Path]) -> list[str]:
    """Return the subset of `paths` that git's own ignore rules would exclude.

    `git check-ignore` is used rather than reimplementing gitignore matching — the whole
    point is to test against git's real behaviour, and gitignore's precedence and negation
    semantics are subtle enough that a reimplementation would be its own source of bugs.

    **`--no-index` is load-bearing, not a detail.** Without it, git skips paths that are
    already tracked, because ignore rules genuinely do not apply to tracked files. That
    would make this check silently useless in the exact way it is meant to prevent: once
    someone `git add -f`s a package past a bad rule, the rule stays broken and this check
    starts passing. `--no-index` asks the question actually worth asking — *would this rule
    exclude this source directory* — independent of what happens to be tracked today. This
    was caught by deliberately restoring the original bad rule and confirming the first
    version of this check did not fire.

    **`-z` and byte-mode I/O are also load-bearing, for a Windows-specific reason.** Passing
    `text=True` wraps stdin in a text stream whose newline translation turns every `\\n` into
    `\\r\\n` on Windows, so git receives `core/logs\\r`, matches nothing, and the check passes
    while verifying literally nothing. NUL-separated bytes have no translation layer to get
    this wrong, and are also the only form correct for a path containing a newline. This was
    found the same way — by running the check against a deliberately broken `.gitignore`
    rather than trusting that a green result meant anything.
    """
    if not paths:
        return []
    rel = [str(p.relative_to(repo)).replace("\\", "/") for p in paths]
    payload = b"\0".join(r.encode("utf-8") for r in rel) + b"\0"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=repo,
        input=payload,
        capture_output=True,
    )
    # Exit 0 = at least one path ignored, 1 = none ignored, anything else is a real error.
    if result.returncode not in (0, 1):
        detail = result.stderr.decode("utf-8", "replace").strip()
        print(f"::error::git check-ignore failed: {detail}", file=sys.stderr)
        raise SystemExit(2)
    return [c.decode("utf-8", "replace") for c in result.stdout.split(b"\0") if c]


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    offenders = ignored_paths(repo, source_directories(repo))

    if offenders:
        print("::error::Source directories are excluded by this repository's own .gitignore.")
        print()
        print("These paths hold source code but git has been told to ignore them, so their")
        print("contents cannot be committed and their absence will never show up as a diff:")
        print()
        for path in sorted(offenders):
            print(f"  {path}")
        print()
        print("This is almost always an unanchored .gitignore rule matching at an unintended")
        print("depth. A rule meant for a directory at the repository root needs a leading")
        print("slash: `/logs/`, not `logs/`. See the comment on that rule in .gitignore for")
        print("the real instance of this that cost the Logs API its entire package.")
        return 1

    print(f"All {len(source_directories(repo))} source directories are committable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
