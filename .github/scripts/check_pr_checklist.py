#!/usr/bin/env python3
"""Parses a PR body for markdown checklist items and fails if any are
unchecked, or if the two highest-stakes items (Forward-Compatibility
Hygiene, Backward-Carrying Capability) are checked with no real
substance behind them.

This is deliberately NOT dependent on real application code existing —
it only reads the PR description text, which means it's genuinely
functional from day one, unlike the per-category static-analysis
checks (check_new_core_api.yml etc.) which need real source files to
inspect and are still scaffolding until then. This script is real,
working CI today.

Exit code 0 = pass, 1 = fail (blocks merge via required-status-check).
"""
import os
import pathlib
import re
import sys

# Bullets that require more than a bare checked box — a real substance
# check, not just "is the box ticked." A tick with no reasoning after
# the colon is exactly the failure mode that made these checkboxes
# advisory-only in the first place.
SUBSTANCE_REQUIRED = [
    "Forward-Compatibility Hygiene",
    "Backward-Carrying Capability",
]
MIN_SUBSTANCE_CHARS = 25  # enough to rule out "n/a" or a bare restatement, not enough to be a real burden


def get_pr_body() -> str:
    body = os.environ.get("PR_BODY", "")
    if not body:
        print("::error::PR_BODY environment variable is empty or unset.")
        sys.exit(1)
    return body


def find_checklist_items(body: str) -> list[tuple[bool, str]]:
    """Returns (is_checked, full_line_text) for every markdown checklist
    item in the PR body, in document order."""
    pattern = re.compile(r"^- \[( |x|X)\]\s*(.+)$", re.MULTILINE)
    return [(m.group(1).lower() == "x", m.group(2).strip()) for m in pattern.finditer(body)]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def load_template_boilerplate(
    template_dir: str = ".github/PULL_REQUEST_TEMPLATE",
) -> set[str]:
    """Every checklist line the templates themselves ship with.

    **Why this exists, because it was a real bug and not a hypothetical one.** The substance
    check originally just measured the text after the colon — but the templates' own wording
    for the two high-stakes items is already ~100 characters long, so an author could tick
    every box, add nothing at all, and sail past a check whose entire purpose is catching
    exactly that. Comparing against the shipped template text is what makes "did a human
    actually write something here" answerable.

    Reads the live templates rather than a copied-in constant, so editing a template can
    never leave this script asserting against wording that no longer exists.
    """
    boilerplate: set[str] = set()
    d = pathlib.Path(template_dir)
    if not d.is_dir():
        # Fail loud rather than silently degrading to the weaker check — a silently
        # weakened required status check is worse than an obviously broken one.
        print(f"::error::{template_dir} not found; cannot distinguish template boilerplate "
              f"from author-written justification. Check the workflow's sparse-checkout.")
        sys.exit(1)
    for f in sorted(d.glob("*.md")):
        for _checked, text in find_checklist_items(f.read_text(encoding="utf-8")):
            after = text.split(":", 1)[1].strip() if ":" in text else text
            boilerplate.add(_normalize(after))
    return boilerplate


def author_substance(text: str, boilerplate: set[str]) -> str:
    """What the author actually added, with any shipped template wording discounted."""
    after_colon = text.split(":", 1)[1].strip() if ":" in text else ""
    norm = _normalize(after_colon)
    if norm in boilerplate:
        return ""  # verbatim template text: nothing was written here
    for bp in boilerplate:
        # The common real case: the author kept the prompt and appended their answer.
        if bp and norm.startswith(bp):
            return norm[len(bp):]
    return after_colon


def main() -> int:
    body = get_pr_body()
    items = find_checklist_items(body)
    boilerplate = load_template_boilerplate(
        os.environ.get("PR_TEMPLATE_DIR", ".github/PULL_REQUEST_TEMPLATE")
    )

    if not items:
        # No checklist found at all — likely means the PR didn't use one
        # of the templates under docs/templates/. Not this script's job
        # to force template usage; a separate check (or human review)
        # catches an unlabeled PR that should have used one.
        print("No checklist items found in PR body — skipping (not a templated PR).")
        return 0

    failures = []

    for is_checked, text in items:
        if not is_checked:
            failures.append(f"UNCHECKED: {text[:100]}")
            continue

        for keyword in SUBSTANCE_REQUIRED:
            if keyword in text:
                author_text = author_substance(text, boilerplate)
                stripped = re.sub(r"[^a-zA-Z0-9]", "", author_text)
                if len(stripped) < MIN_SUBSTANCE_CHARS:
                    failures.append(
                        f"CHECKED BUT NO SUBSTANCE: '{keyword}' item is checked, but once the "
                        f"template's own wording is discounted there are under "
                        f"{MIN_SUBSTANCE_CHARS} real characters of justification left. Ticking "
                        f"the box without adding your own reasoning is exactly the failure mode "
                        f"this check exists to catch."
                    )

    if failures:
        print("::error::PR checklist verification failed:")
        for f in failures:
            print(f"  - {f}")
        print(
            "\nEvery checklist item from the PR template must be explicitly checked, "
            "and the two hygiene items (Forward-Compatibility Hygiene, Backward-Carrying "
            "Capability) need real reasoning after the colon — not just a tick. "
            "If an item genuinely doesn't apply, check it and say why in the text."
        )
        return 1

    print(f"All {len(items)} checklist items verified: checked, with substance where required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
