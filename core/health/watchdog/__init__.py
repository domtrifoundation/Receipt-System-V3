"""Watchdog — liveness monitoring, Health API's sub-API.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1); re-exporting `KickRegistry` or
`TimeoutDetector` here would quietly make them look like the supported entry point when the
supported entry point is the gRPC surface the parent's `service.py` exposes.

Nothing in this package restarts anything, and that absence is deliberate
(`v3-deepdive-34-watchdog.md` §1): Watchdog detects and reports, Supervisor acts.
"""
