"""The automated enforcement of "no local passwords, ever, under any circumstance" (§4, §12).

The deep-dive's §11 asks for this by name: "a static/lint check across the entire codebase
for any code path resembling password hashing, a password input field, or a 'confirm with
your password' prompt — the concrete enforcement of §4's own opening principle, not just a
documented intention."

This is that check. It runs over the whole repository, not only over `core/auth/`, because
the failure mode being guarded against is someone adding a password *somewhere else* as a
quick fix for an edge case and assuming Auth is the only place the rule applies.

Prose that *names* the rule is exempt — this file, docstrings, and comments explaining why
no password exists all have to be able to say the word. What is banned is a password as a
working concept: a field, a column, a hashing call, a verification helper.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Directories with nothing hand-written in them.
_SKIP_DIRS = {
    ".git", "__pycache__", ".nox", ".venv", "venv", "node_modules", "generated",
    "data", "models", "config",
}

#: Libraries whose entire purpose is password hashing. Importing any of them is the
#: unambiguous signal that a password now exists somewhere.
_BANNED_IMPORTS = {
    "bcrypt", "passlib", "argon2", "argon2_cffi", "scrypt", "pbkdf2", "werkzeug.security",
}

#: Identifier patterns that mean a password is being handled, as opposed to discussed.
#: `password_hash`, `check_password`, `set_password`, `pwd_hash`, `PASSWORD_MIN_LENGTH`.
_BANNED_IDENTIFIER = re.compile(
    r"(?i)\b(?:password|passwd|pwd)s?_?(?:hash|hashes|digest|salt|check|verify|reset|"
    r"field|column|input|min_length|max_length)\b"
    r"|\b(?:check|verify|set|hash|validate|store)_(?:password|passwd|pwd)\b"
)


def _python_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*.py"):
        if _SKIP_DIRS & set(path.parts):
            continue
        files.append(path)
    return files


def _identifiers(tree: ast.AST) -> list[str]:
    """Every name the code actually defines or uses — deliberately not the raw text, so a
    docstring explaining the rule does not trip the check that enforces it."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.append(node.arg)
    return names


def test_repository_has_no_password_handling_identifier():
    offenders: list[str] = []
    for path in _python_files():
        if path == Path(__file__):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file is another test's problem
            continue
        for name in _identifiers(tree):
            if _BANNED_IDENTIFIER.search(name):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert not offenders, (
        "no local password authentication exists in this design, under any circumstance "
        f"(deep-dive §4). Found: {offenders}"
    )


def test_no_password_hashing_library_is_imported_anywhere():
    offenders: list[str] = []
    for path in _python_files():
        if path == Path(__file__):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                root = module.split(".")[0]
                if root in _BANNED_IMPORTS or module in _BANNED_IMPORTS:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
    assert not offenders, f"password-hashing dependency found: {offenders}"


def test_the_auth_schema_has_no_password_column():
    """The structural half: there is no column a password could be written into, so this
    cannot be reintroduced by an application-layer change alone (`docs/PRINCIPLES.md` §4.5).
    """
    from core.auth import store

    schema = store._SCHEMA.lower()  # noqa: SLF001 - asserting on the schema is the point
    for banned in ("password", "passwd", "pwd"):
        assert banned not in schema


def test_the_checker_would_actually_catch_a_violation():
    """A guard that cannot fail is not a guard. This confirms the pattern matches the thing
    it exists to match, so the two tests above passing means something."""
    for sample in ("password_hash", "check_password", "PASSWORD_MIN_LENGTH", "pwd_salt"):
        assert _BANNED_IDENTIFIER.search(sample), sample
    for benign in ("passwordless", "auth_methods", "passkey_provider"):
        assert not _BANNED_IDENTIFIER.search(benign), benign


@pytest.mark.parametrize("path", ["core/auth/auth.proto"])
def test_the_proto_surface_offers_no_password_field(path):
    text = (REPO_ROOT / path).read_text(encoding="utf-8").lower()
    for line in text.splitlines():
        # Comments — whole-line or trailing — may name the rule; the declarations may not.
        declaration = line.split("//", 1)[0].strip()
        assert "password" not in declaration, line
