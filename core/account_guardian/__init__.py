"""Account Guardian API — the user-facing privacy and account security center.

Deliberately empty of re-exports, same reasoning as `core/audit/__init__.py` and
`core/logs/__init__.py`: `contracts.py` is the only module anything outside this package
imports from (`docs/PRINCIPLES.md` §1.1), and re-exporting `service.py`'s servicer here
would quietly make `from core.account_guardian import AccountGuardianServicer` look like the
supported entry point when the supported entry point is `service.serve()`.
"""
