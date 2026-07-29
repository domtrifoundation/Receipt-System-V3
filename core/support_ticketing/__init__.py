"""Support Ticketing API — a real in-app ticket lifecycle.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1).

This API owns ticket state and conversation content, never notification delivery
(`v3-deepdive-52-support-ticketing.md` §1) — a new message routes through Notifications the
same way any other in-app event does.
"""
