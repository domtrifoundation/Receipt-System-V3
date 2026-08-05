"""Migration API — the schema-version chain.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1).

This API owns no rollback machinery (`v3-deepdive-23-migration-api.md` §1): migrations write
through Persistence's normal path, so every one is already atomic and Historian-revertable.
"""
