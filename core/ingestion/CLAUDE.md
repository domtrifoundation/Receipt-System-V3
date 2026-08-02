# Ingestion API

Ingestion API's job: acquire a source file from wherever it comes from, normalize it into one or more base images, and hand those off to Preprocessing/OCR.

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 acquired receipts by globbing a configured folder and excluding the archive. V2 added Google Drive as a real second channel (`google_drive.py`, OAuth plus folder-ID polling) alongside the watched folder. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a03.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-04-ingestion-api.md`](../../docs/apis/v3-deepdive-04-ingestion-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide OCR-readability transforms** — grayscale/contrast/threshold variant generation is entirely Preprocessing API's job (§1 of that deep-dive already draws this line from its own side).
- **own malware/content-safety scanning logic** — it calls the Content Security API (file 01, #26) as every other untrusted-content entry point does; scanning logic lives there once, not duplicated per caller.
- **own the reimport/edit-flow-back-in path** — that's Persistence's Reimport sub-API (file 01, #5), even though it's conceptually "receiving a file from outside the system" the same way Ingestion's other channels are. It stays there because its actual job (diff against canonical state, resolve conflicts, apply through the normal write path) is a Persistence-write concern, not an acquisition/normalization one — already resolved and corrected into file 01/03 in this session's prior discussion.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Every source is an independently enableable Provider Registry entry. A self-hosted install with no Drive configured must degrade to direct-upload-only cleanly, never error. Drive credentials go through a swappable credential-provider interface: service account is the only strategy usable today, per-user OAuth is built behind the same interface and switches on by config once Google's verification clears — not a rewrite at that point, and not something to hardcode around now.
