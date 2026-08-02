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

# Present in a normal end-user install. Anything genuinely new and
# user-facing (a new top-level data directory, a new launcher script)
# gets added here explicitly, in the same PR that adds it.
SHIPPED_ALLOWLIST = {
    "core",
    "services",
    "webapp",
    "config",
    "data",
    "models",
    "start.bat",
    "start.sh",
    "LICENSE",
    "README.md",
    ".gitignore",
    # --- classified in Phase 1, when the real tree first existed -------------
    "supervisor",       # Supervisor is *deployed* outside every release clone
                        # (docs/PROCESS_TOPOLOGY.md §1), but its source still ships inside
                        # the clone the installer pulls — that is where the top-level copy
                        # is placed from. Stripping it would leave nothing to launch with.
    "common",           # runtime code imported by services (common/frozen_dict.py is the
                        # one centralized FrozenDict shim, docs/PRINCIPLES.md §2.1).
    "assets",           # codename ASCII art, rendered at runtime by the Boot Sequence
                        # screen and the persistent TUI header, and retained for every
                        # codename indefinitely (docs/MAINTENANCE.md §1) — a running
                        # instance genuinely needs its own version's banner.
    "requirements.txt", # the aggregate/dev-convenience set — what a contributor installs into
                        # one venv so the whole test suite runs in a single environment.
                        # Production venvs are NOT built from this: per-service venvs compose
                        # common/requirements.txt plus each service's own requirements.txt
                        # (docs/VENV_AND_IMPORTS.md §4), which ship inside core/ and services/
                        # and are therefore already covered by those entries above. Still
                        # classified shipped because a running instance is a clone, and a clone
                        # is also where a re-provision would be run from. Note
                        # requirements-dev.txt and pyproject.toml are dev-only below — that
                        # split is the point.
}

# Stripped by strip_development_content() in normal mode. This is the
# authoritative list — Setup API's own dev_mode_strip.py imports these
# same constants rather than this script importing a separate copy,
# so there is exactly one place this list is actually defined.
DEV_ONLY_STRIP_LIST = {
    "CONTRIBUTING.md",
    "docs",
    "tests",
    ".github",  # covers PULL_REQUEST_TEMPLATE/, workflows/, scripts/, instructions/ —
                # entire directory tree, not enumerated file-by-file, so a NEW file added
                # anywhere under .github/ is automatically covered without a list update
    "pyproject.toml",  # dev/build tooling config, not runtime code
    "requirements-dev.txt",
    # --- classified in Phase 1, when the real tree first existed -------------
    "pytest.ini",   # test-runner config; meaningless without tests/, already dev-only.
    "CLAUDE.md",    # development guidance for LLM-assisted sessions. Nothing in a running
                    # end-user instance reads it. Worth being explicit about *why* this is
                    # dev-only despite being load-bearing: docs/CLAUDE_MD_GUIDE.md §2.1
                    # makes these files the artifact that survives the deep-dive corpus
                    # being removed — important to development, irrelevant at runtime, and
                    # those are different questions.
    # --- classified in Phase 1.5, when multi-version validation was set up ---------
    "noxfile.py",   # drives `nox -s forward_compat` (docs/MAINTENANCE.md's
                    # Forward-Compatibility Validation section) — a dev-time test-runner
                    # invocation, same category as pytest.ini, never invoked by the shipped
                    # program itself. `.nox/`'s own venv cache never reaches git at all
                    # (self-ignoring on top of an explicit root .gitignore entry), so it was
                    # never a classification question the way this file is.
}

# A real gap this top-level check cannot see, recorded here rather than left implicit:
# CLAUDE.md files also exist in every API and sub-API folder (52 of them as of Phase 1),
# nested under core/, services/, webapp/, and supervisor/ — all of which ship. A top-level
# entry name cannot express "strip this filename wherever it appears," so
# strip_development_content() needs an explicit nested-pattern rule for CLAUDE.md, not just
# the top-level list. Flagged for whoever implements Setup API's own dev_mode_strip.py:
# without it, every end-user install carries 52 development-only files it will never read.


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
