#!/usr/bin/env python3
"""Confirms every top-level file/directory in the repo is explicitly
classified as either shipped (present in a normal end-user install) or
dev-only (stripped by strip_development_content()) — never left
unclassified.

This is deliberately NOT "does the strip-list contain every known
dev-only pattern" — that would just be a second hardcoded list at risk
of the exact same drift `.github/scripts/` and `.github/instructions/`
already caused twice. Instead: a closed-world check. Every top-level
entry must appear in exactly one of the two sets below. A new
top-level file or directory that isn't in either one fails CI
immediately, forcing a human decision the moment it's added — not
"the list doesn't happen to mention it yet," but "this can't merge
until someone says which bucket it belongs in."

Run locally: python .github/scripts/check_stripped_content_list.py
Exit code 0 = every top-level entry classified, 1 = something isn't.
"""
import subprocess
import sys
from pathlib import Path

# The lists live in services/setup/dev_mode_strip.py and are imported from there, so there is
# exactly one place they are actually defined.
#
# This direction is the reverse of what this script originally claimed ("Setup API's own
# dev_mode_strip.py imports these same constants"). The goal was right, the direction could not
# work: `.github/` is itself in DEV_ONLY_STRIP_LIST, so strip_development_content() would have
# been importing its own strip list out of the directory it is about to delete — and Setup is
# idempotent by design while Update API strips every fresh clone, so the second run would find
# the import target gone. `services/` ships, so the definition lives there instead.
#
# sys.path needs the repo root explicitly: this script is executed by path
# (`python .github/scripts/check_stripped_content_list.py`), which puts `.github/scripts/` on
# sys.path[0], not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.setup.dev_mode_strip import (  # noqa: E402
    DEV_ONLY_STRIP_LIST,
    NESTED_STRIP_FILENAMES,
    SHIPPED_ALLOWLIST,
)


def get_toplevel_entries() -> set[str]:
    """Real git-tracked top-level entries, not a filesystem walk — this
    deliberately ignores anything gitignored (build artifacts, __pycache__,
    a local venv) since those were never a classification question to
    begin with."""
    result = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def main() -> int:
    try:
        entries = get_toplevel_entries()
    except subprocess.CalledProcessError as e:
        print(f"::error::Couldn't read git tree: {e}")
        return 1

    classified = SHIPPED_ALLOWLIST | DEV_ONLY_STRIP_LIST
    unclassified = entries - classified
    overlap = SHIPPED_ALLOWLIST & DEV_ONLY_STRIP_LIST

    failed = False

    if overlap:
        print(f"::error::These entries are in BOTH lists, which is itself a bug: {sorted(overlap)}")
        failed = True

    # A nested-strip filename is removed *wherever it appears* beneath the clone root, so one
    # that is also shipped would delete shipped content everywhere it occurs — a far worse
    # failure than the top-level overlap above, and invisible to that check because the two
    # lists genuinely do not intersect for it.
    nested_shipped = NESTED_STRIP_FILENAMES & SHIPPED_ALLOWLIST
    if nested_shipped:
        print(
            "::error::These are stripped from every directory but also classified shipped, "
            f"which would delete shipped content repo-wide: {sorted(nested_shipped)}"
        )
        failed = True

    if unclassified:
        print("::error::Unclassified top-level entries found — every one needs to be added to either")
        print("SHIPPED_ALLOWLIST or DEV_ONLY_STRIP_LIST in this same script, in this same PR:")
        for e in sorted(unclassified):
            print(f"  - {e}")
        print("\nThis is exactly the drift that already happened twice with .github/scripts/ and")
        print(".github/instructions/ before this check existed. Classify it now, in this PR.")
        failed = True

    if not failed:
        print(f"All {len(entries)} top-level entries classified: "
              f"{len(entries & SHIPPED_ALLOWLIST)} shipped, {len(entries & DEV_ONLY_STRIP_LIST)} dev-only.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
