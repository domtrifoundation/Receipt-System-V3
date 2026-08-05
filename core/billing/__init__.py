"""Billing & Subscription API.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1).

**Self-hosted licensing is deliberately not here** (`v3-deepdive-22-billing-subscription-api.md`
§1). Putting license validation inside this API would ship it inside every self-hosted release
clone, on the exact machine it is meant to check, fully readable and patchable by the person it
validates — a check that is not a check. That is Keymaster, a separate closed system.
"""
