"""Background Workers API — the generic scheduling and dispatch substrate.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1), and re-exporting `JobScheduler` here would
quietly make `from core.background_workers import JobScheduler` look like the supported entry
point when a domain API's real entry point is registering a job against `JobRegistry`.

This API owns no business logic (`v3-deepdive-12-background-workers-api.md` §1). A job that
checks VAT math belongs to Reconciliation; this package only decides how and when it runs.
"""
