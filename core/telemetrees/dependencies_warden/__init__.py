"""Dependencies Warden — Telemetrees API sub-API.

Deliberately empty of re-exports; the parent's `contracts.py` is the import surface
(`docs/PRINCIPLES.md` §1.1). This sub-API watches, interprets and reports — it never decides
whether to adopt what it finds, and it never runs a test itself (§1). Proving Grounds does.
"""
