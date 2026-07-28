"""Health API — live status, the resource commitment ledger, and capability drift.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1), and re-exporting `ResourceLedger` here would
quietly make `from core.health import ResourceLedger` look like the supported entry point when
the supported entry point is the gRPC service in `service.py`.

Health reports; it never decides (`v3-deepdive-20-health-api.md` §1). Nothing in this package
gates a rollout or restarts a process — Supervisor owns both, consuming what is reported here.
"""
