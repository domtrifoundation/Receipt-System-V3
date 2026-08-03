# Format Normalization

**Sub-API of Ingestion API** (`core/ingestion/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Format Normalization owns turning whatever arrives through any Ingestion source (direct upload, Drive, the in-browser scanner) into the one finished base image Preprocessing and the archival blob store both consume.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 genuinely normalized a wide input set — `pymupdf`/`pdfplumber` for PDF and Pillow for images, both pinned in its own `requirements.txt`. V1 accepted images and PDFs but delegated the decoding entirely to its host tooling rather than implementing it, so V1 is not an ancestor here. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-42-format-normalization.md`](../../../docs/apis/v3-deepdive-42-format-normalization.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide OCR-readability transforms** — grayscale/contrast/threshold variant generation is entirely Preprocessing's own job; this sub-API produces one faithful base image, never an OCR-optimized one.
- **scan for malicious content itself** — Content Security (§5 below) does that; this sub-API calls it, never re-implements scanning logic.
- **decide the archival codec choice itself** — a single, owner-selected, system-wide config value (§3); this sub-API applies whichever codec is configured, never picks one on its own.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Output branches two ways from one common source, not sequentially: the archival re-encode that gets hashed and stored, and the base image fed to Preprocessing. The content-address hash is computed over the *original uploaded bytes*, before re-encoding. One codec for the whole install, owner-selected — never a per-user or per-tier lever. `pillow-heif` is the one necessary plugin (Pillow's only real gap, for HEVC licensing reasons) and has a real CVE history, which is why it stays on Proving Grounds' radar.

- **`raster.py` delegates to `core.preprocessing.raster`'s own `sniff_format`/
  `decode_image_bytes`/`encode_image_png`** rather than re-implementing format detection
  or decode — this sub-API's own job on top is page enumeration (a real `fitz.open()`
  page-count call) for multi-page PDFs, confirmed live against a real 3-page synthetic
  PDF producing exactly 3 real PNG-encoded pages.
- **`codecs.py`'s AVIF/WebP re-encode is confirmed live**, including a genuine
  HEIC-source round-trip (`pillow_heif`-decoded, then re-encoded to AVIF) — not assumed
  from Pillow's own documentation. `pillow_heif.register_heif_opener()` is called
  directly inside this module rather than relied upon as an import-order side effect of
  `core.preprocessing.raster` having already run it elsewhere.
- **`archive_extract.py`'s directory-entry filtering (`info.is_dir()`) is confirmed
  live** against a real zip containing an empty directory entry — `list_entries`/
  `extract_entries` both correctly skip it rather than yielding an empty-bytes "file."

## Implementation status

Implemented this session — `errors.py`, `raster.py`, `codecs.py`, `archive_extract.py`.
All three modules validated live against real synthetic inputs (a multi-page PDF, a
real HEIC image, a real zip archive) — see the parent `core/ingestion/CLAUDE.md` and its
own test suite for the full pipeline this sub-API feeds into.
