"""Multi-version validation for anything touching this project's own
Forward-Compatibility Pattern (`docs/PRINCIPLES.md` §3.3-3.3.1).

Run `nox -s forward_compat` to validate against both 3.14 and 3.15.
Run `nox -s forward_compat-3.15` to target just the newer interpreter.
Run `nox -s forward_compat_316` manually once a 3.16 build is available locally.

This is deliberately NOT the full test suite — it runs only tests marked
`@pytest.mark.forward_compat` (registered in `pytest.ini`), kept fast enough to actually run
at the real cadence: after each API's own implementation, and as a required gate before
`x03.00.00` (see `docs/MAINTENANCE.md`'s Forward-Compatibility Validation section for the
full policy — this file is the mechanism, that section is the reasoning and the cadence).

Requires both interpreters to actually be installed and discoverable. On Windows, nox finds
them through the `py` launcher (`py -3.14`, `py -3.15`) automatically — no PATH entry named
`python3.14`/`python3.15` is needed there, unlike Linux/macOS where those names are what a
normal build or a pyenv install produces and nox looks for directly. If an interpreter isn't
installed, this session fails loudly rather than silently skipping it — a missing
interpreter is a real environment problem to fix, not something to quietly work around.

**Why this session installs a narrow, explicit dependency set rather than
`session.install("-e", ".")` or `-r requirements.txt`, confirmed rather than assumed while
setting this up**: `grpcio`/`grpcio-tools` (in `requirements.txt`) have no prebuilt wheel yet
for CPython 3.15 — pip falls back to building the full C++ grpc/abseil/protobuf stack from
source, which is slow even when the local toolchain can do it at all, and this environment's
own attempt to build it against 3.15 beta 4 failed outright. That's a real, current Day-0 gap
in an upstream dependency, tracked in `docs/MAINTENANCE.md` §3's inventory — not a reason to
make *this* check depend on it. None of the tests currently marked `forward_compat` import
`grpc` at all, so this session installs exactly what they need: `pytest`, and `frozendict`
(with the same `python_version < '3.15'` marker `requirements.txt` uses, so it's correctly
skipped on 3.15 rather than needlessly installed). **If a future `forward_compat`-marked
test needs a package requirements.txt also carries, add that package here explicitly by
name — not by switching this session over to installing requirements.txt wholesale**, since
that reintroduces exactly the coupling this paragraph explains avoiding.
"""

import nox

PYTHON_VERSIONS = ["3.14", "3.15"]

#: Kept explicit and minimal rather than derived from requirements.txt — see the module
#: docstring above for why. Every entry here is something a currently forward_compat-marked
#: test actually imports.
FORWARD_COMPAT_DEPS = [
    "pytest",
    "frozendict; python_version < '3.15'",
    # Needed at *collection* time, not by any forward_compat-marked test itself. `-m
    # forward_compat` deselects tests, but pytest imports every test module before it can
    # evaluate a marker, so an unmarked module whose import chain reaches `rapidfuzz`
    # (tests/unit/core/{geo_address,matching,account_guardian,reconciliation}/... ->
    # core.geo_address.reverse_check) raises a collection error that aborts the whole
    # session. Adding it by name is what the module docstring above prescribes; the
    # alternative of installing requirements.txt wholesale would drag in grpcio, which is
    # the exact coupling that docstring explains avoiding.
    "rapidfuzz>=3.0",
    # Same reasoning, same fix: tests/unit/services/update/test_keymaster_client.py -> import
    # chain -> services.update.keymaster_client -> module-scope `import httpx`. httpx has real
    # 3.15 wheels (unlike grpcio), so this is a genuinely cheap addition, not a repeat of the
    # grpcio problem this session's own dependency selection exists to avoid.
    "httpx>=0.27",
]


@nox.session(python=PYTHON_VERSIONS)
def forward_compat(session):
    """The targeted forward-compatibility test subset, per interpreter."""
    session.install(*FORWARD_COMPAT_DEPS)
    session.run("pytest", "-m", "forward_compat", "-v")


@nox.session(python="3.16", venv_backend="none")
def forward_compat_316(session):
    """Separate, non-parameterized session for 3.16 specifically, since it's built from
    source rather than a normal pip-installable interpreter. Run manually — genuinely
    optional, unlike 3.15's required status (`docs/PRINCIPLES.md` §3.3.1).

    `venv_backend="none"` because there is no `pip`-installable 3.16 to create a venv
    from — this session runs directly against whatever `python3.16`/`py -3.16` already has
    installed on PATH, which the person running it is responsible for having set up with
    `FORWARD_COMPAT_DEPS` available themselves.
    """
    session.run("pytest", "-m", "forward_compat", "-v")
