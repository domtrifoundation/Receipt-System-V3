# Content Security API

Content Security owns **scanning every untrusted incoming file** — real file-type verification (magic bytes, never trusting an extension or client-supplied MIME type), malware/exploit scanning, polyglot detection, and container-level bomb checks for archives.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no file-type verification, malware scanning, polyglot detection, or archive-bomb checking — the only occurrence of the word "antivirus" in its source is a help string about engines failing to start. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-27-content-security-api.md`](../../docs/apis/v3-deepdive-27-content-security-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide what happens after a rejection** — flagging, notifying, and any staff review of a rejected file are Review/Flagging's and Notifications' own jobs; this API's contract is a pass/fail verdict plus detail, not a downstream workflow.
- **get bypassed or reimplemented per-caller** — Ingestion calls it (its deep-dive §6, explicitly fail-closed with no local bypass path), and Persistence's Reimport calls the exact same shared logic for its own uploads (file 01) rather than either API rolling its own scanning.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Fail-closed is a contract-level guarantee, not a caller convention (`docs/PRINCIPLES.md` §4.2): if the scan call fails, times out, or the service is briefly unavailable, every caller treats the file as unscanned and therefore unsafe. Archive-bomb detection reads `zipfile.infolist()` metadata *before* any extraction — never unpack a hostile archive to measure it. Two passes, not one: the container, then each file it yielded.
