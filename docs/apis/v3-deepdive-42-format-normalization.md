# V3 Deep Dive: Format Normalization (sub-API)

**Parent:** `v3-deepdive-04-ingestion-api.md` §5 (the section this document expands and replaces). Explicitly labeled "Sub-capability:" in file 01 — a real mislabeling caught during a corpus-wide sweep: it has its own package path, real depth (codec selection, HEIC/AVIF/PDF/zip handling, hash-on-original-bytes), and cross-references from Persistence, Content Security, and Telemetrees. It should have been called a sub-API from the start.

**Companion files:** `v3-deepdive-13-persistence-api.md` §3.3-§4.1 (the `BlobRef`/`BlobLocation` scheme this feeds), `v3-deepdive-27-content-security-api.md` §3.1 (the 3.16 zip remediation capability), `v3-deepdive-37-dependencies-warden.md` (tracks `pillow-heif`'s own CVE-relevant update cadence).

**Status:** New dedicated document, corrected out of Ingestion's own deep-dive and out of a mislabeling in file 01.

---

## 1. Scope & boundary

Format Normalization owns turning whatever arrives through any Ingestion source (direct upload, Drive, the in-browser scanner) into the one finished base image Preprocessing and the archival blob store both consume. It does not:
- **decide OCR-readability transforms** — grayscale/contrast/threshold variant generation is entirely Preprocessing's own job; this sub-API produces one faithful base image, never an OCR-optimized one.
- **scan for malicious content itself** — Content Security (§5 below) does that; this sub-API calls it, never re-implements scanning logic.
- **decide the archival codec choice itself** — a single, owner-selected, system-wide config value (§3); this sub-API applies whichever codec is configured, never picks one on its own.

---

## 2. Package layout

```
core/ingestion/format_normalization/
  __init__.py
  raster.py                     # PDF rendering, delegates to Preprocessing's own raster.py for image output shape parity
  codecs.py                       # archival re-encode — single owner-selected codec, see §3
  archive_extract.py                # zip handling, see §4
  errors.py
```

---

## 3. Archival re-encode — one codec, owner-selected, hash on original bytes
Resolved and corrected into file 01/03 in an earlier session; restated here as the authoritative detail, now in this sub-API's own document rather than buried in Ingestion's:
- **One codec for the whole install** (WebP or AVIF), an owner-level system-wide config value, not a per-user/tier lever — archival format is an infrastructure decision (disk footprint, long-term compatibility), not a monetization knob.
- **Encoding via Pillow's native AVIF support (11.3+) or its native WebP support** — the same call either way, trivial to switch the owner's choice without maintaining two separate dependency paths.
- **Hardware-accelerated encode (Intel Quick Sync/MFX, NVIDIA NVENC, AMD VCN) explicitly not adopted.** AV1 hardware *decode* is broadly available (Intel since Tiger Lake/11th-gen), but AV1 hardware *encode* — the only vendor-accelerated path relevant to AVIF, since AVIF is a single AV1 intra-frame in a HEIF container — needs meaningfully newer hardware across every vendor (roughly 2022-2023+), and no vendor has ever shipped a WebP hardware encoder at all. Software encode (libavif/aom, with SVT-AV1 available as a faster backend) is fast enough at this workload's actual volume — a handful of images per run, not video frame rates — and avoids hand-building session management around three separate vendor SDKs with no Python bindings.
- **The content-address hash is computed over the original uploaded bytes, before re-encoding** — an immutable lookup/dedup key decoupled from whichever codec is currently the system-wide choice, resolved to the actual on-disk `physical_hash` via Persistence's own `BlobLocation` mapping (its deep-dive §3.3) — this sub-API produces the re-encoded bytes, Persistence owns the identity/location split.
- **Cross-user batching of encode work explicitly rejected**, even though a single intra-frame encode is provably safe from cross-user data leakage (no motion-compensation/reference-frame state exists in still-image intra encoding). Rejected anyway: a "safe today because we checked the codec" exception to structural per-user isolation is exactly the kind of thing that's easy to accidentally break later. What legitimately still batches: multiple images from *one* user's *one* run, processed sequentially through a reused encoder object, never interleaved with another user's data.
- **Normalization output branches two ways from one common source, not sequentially**: (a) archival re-encode → hashed → stored as the permanent Persistence blob, and (b) fed separately to Preprocessing's pipeline — neither depends on the other's output, avoiding both compounded lossy re-compression and accidentally archiving an OCR-optimized rather than faithful visual copy.

---

## 4. Rasterization and image format coverage

### 4.1 Rasterization (PDF and non-image inputs)
`PyMuPDF`/`fitz` — a self-contained C-extension wheel, page rendering plus embedded-image extraction, no `poppler`/`ffmpeg` needed. Produces the base image(s) that flow into Preprocessing exactly the same way the scanner's corrected capture or a directly-uploaded image already does — same `NormalizedImage` contract regardless of which source produced it, so Preprocessing never needs to know or care which channel an image arrived through.

### 4.2 Image format coverage
**Pillow already natively covers essentially every image format in existence** — JPEG, PNG, WebP, GIF, TIFF, BMP, ICO, PSD, PPM, PCX, EPS, and 30+ more — plus **native AVIF read/write built directly into Pillow itself since 11.3** (no separate plugin needed; `pillow-avif-plugin` is now obsolete guidance). The one real gap is HEIC/HEIF (kept out of Pillow core for HEVC licensing reasons), which is exactly why `pillow-heif` is the one necessary plugin on top of Pillow, not a separate solution — genuinely needed given this project's actual input medium is predominantly iPhone photos, which default to HEIC. `pillow-heif` recently dropped its own AVIF support specifically because Pillow absorbed it natively — a nice confirmation this dependency picture is current, not stale. Camera RAW formats (CR2/NEF/ARW) explicitly out of scope unless it becomes a real need later. Lightweight Python-native stack throughout — deliberately not `ffmpeg`, since none of this needs video/audio transcoding capability and pulling in one large external binary for formats already well-covered by focused wheels would be the wrong-sized tool.

**Format-decoding libraries are part of the attack surface, not just a feature dependency** — a real recent CVE in `pillow-heif` (integer overflow → heap out-of-bounds read) is a concrete, non-hypothetical reason these specific libraries stay on Proving Grounds' update-testing radar (Telemetrees deep-dive §3.1), given their whole job is parsing untrusted uploaded bytes.

---

## 5. Zip archives (bulk upload batches)
Python's built-in `zipfile`, zero extra dependency. Content Security's container-level bomb check (`infolist()` metadata — compression ratio, cumulative uncompressed total, entry count, nesting depth) runs *before* any extraction; each file extracted from a cleared zip still gets its own individual Content Security pass afterward — a bomb-free container could still smuggle one bad file among good ones (Content Security's own deep-dive already specifies this two-pass model; this sub-API calls it, doesn't reimplement it). **On Python 3.16+, a zip containing one bad member no longer means rejecting the whole batch upload** — Content Security's own `zipfile.remove()`/`.repack()`-based selective remediation (its deep-dive §3.1, feature-detected via `hasattr`, not version-gated) strips just the offending member and lets normalization proceed with the rest of a bulk upload, rather than forcing a full re-upload over one bad file in an otherwise-legitimate batch. This sub-API doesn't implement that remediation itself — it's entirely Content Security's own capability — but it's worth knowing this is why a partially-bad bulk upload might come back as "processed, minus one file" instead of "rejected entirely" once that Python version is in play.

Content Security integration itself (every `SourceFile` scanned before this sub-API touches it, fail-closed if the scan can't be verified) is Ingestion's own concern, described at that document's own §6 — worth cross-referencing rather than duplicating, since the actual scanning relationship doesn't change based on which sub-API is asking for it.

---

## 6. Asyncio
File parsing (`PyMuPDF`, Pillow, `pillow-heif`) is CPU-bound but typically fast for a single file — not worth its own executor-dispatch discussion at this workload's actual scale, consistent with Ingestion's own parent-level conclusion (its deep-dive §7). The archival encode step is the one place worth a real `run_in_executor` dispatch, given encoding cost scales with image size and resolution more than the other steps here.

---

## 7. Testing hooks
- **Codec-switch safety test**: confirms changing the owner's system-wide codec choice never breaks an existing blob reference — direct validation of §3's `logical_id`/`physical_hash` split holding under a real codec change, not just reasoned about.
- **Format-decoding fuzz pass**: malformed/truncated HEIC, AVIF, and PDF inputs fed through this sub-API's own parsing path — a standing regression suite given §4.2's real CVE history, not a one-time check.
- **Cross-user batching isolation test**: confirms encoder-object reuse never interleaves two different users' image data within one batch, even under concurrent multi-user load.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- **SVT-AV1 vs. libaom as the default software AVIF backend, resolved: SVT-AV1.** The more actively developed, faster modern encoder (Intel/Netflix-backed) — a real, defensible default given this workload's own throughput needs, not a coin flip between the two viable options.
- **HEIC-to-archival-format round-trip fidelity, remains a genuine pre-launch bench task, not a design gap.** Whether any real, measurable quality loss occurs needs actual real iPhone photos to check against — an empirical fact waiting on real data, not something this document can resolve by reasoning alone.
