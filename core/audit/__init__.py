"""Audit/Event Log API — the record of privileged, security-relevant actions.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1), and re-exporting the writer or the query
class here would quietly make `from core.audit import AuditWriter` look like the supported
entry point when the supported entry point is the gRPC service in `service.py`.
"""
