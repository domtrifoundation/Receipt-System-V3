"""Real file-type verification via magic bytes (§1) — never an extension, never a
client-supplied MIME type.

This is deliberately the first check in the pipeline (`pipeline.py`) and deliberately pure,
synchronous, in-memory work over bytes already received: there is no network call and no
subprocess here, which is why it runs before any provider is even consulted — a caller gets
the real detected type back even in the "no scan provider is available" fail-closed case,
because knowing what a file actually is does not depend on whether ClamAV happens to be
installed.

`MAGIC_SIGNATURES` is a module-level lookup table nothing should ever write, so it is a
`FrozenDict`, not a plain `dict` (`docs/PRINCIPLES.md` §2.1.1).
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import DetectedFileType

#: mime type -> (byte offset, signature bytes). Ordered by how the table is defined, but
#: `detect()` itself always tries the longest, most specific signatures first regardless of
#: iteration order, so this dict's own order is not load-bearing.
MAGIC_SIGNATURES: FrozenDict = FrozenDict(
    {
        "application/pdf": (0, b"%PDF-"),
        "image/png": (0, b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": (0, b"\xff\xd8\xff"),
        "image/gif": (0, b"GIF8"),
        "image/bmp": (0, b"BM"),
        "image/tiff": (0, b"II*\x00"),
        # Big-endian TIFF shares a mime type with little-endian above; both are real, both
        # occur (Android/iOS camera output varies), so both signatures are checked in
        # `detect()` even though only one appears in this table's own keys.
        "application/zip": (0, b"PK\x03\x04"),
        "application/gzip": (0, b"\x1f\x8b"),
        "application/x-rar-compressed": (0, b"Rar!\x1a\x07"),
        "application/x-7z-compressed": (0, b"7z\xbc\xaf\x27\x1c"),
    }
)

#: A handful of formats need a second variant of the same format at the same offset
#: (big-endian TIFF) or a distinct sub-signature of a format already in the main table (an
#: empty or spanned zip archive). Kept out of `MAGIC_SIGNATURES` itself because that table's
#: own shape — one offset, one signature, one mime type — stays simple for the common case;
#: these are the real exceptions, not the rule. WEBP is deliberately *not* here: it needs two
#: anchors (`RIFF` at offset 0 *and* `WEBP` at offset 8) checked together, and `_detect_webp`
#: below is what does that honestly rather than matching on `WEBP` alone and risking a false
#: positive against any other RIFF-family container (AVI, WAV) that happens to share the
#: four-byte tag at a coincidental offset.
_EXTRA_SIGNATURES: tuple[tuple[str, int, bytes], ...] = (
    ("image/tiff", 0, b"MM\x00*"),
    ("application/zip", 0, b"PK\x05\x06"),  # empty archive
    ("application/zip", 0, b"PK\x07\x08"),  # spanned archive
)

#: Longest signatures first, so a shorter, less specific prefix (gzip's two bytes) never wins
#: over a longer, more specific one that happens to start the same way.
_ALL_SIGNATURES: tuple[tuple[str, int, bytes], ...] = tuple(
    sorted(
        (
            *((mime, offset, sig) for mime, (offset, sig) in MAGIC_SIGNATURES.items()),
            *_EXTRA_SIGNATURES,
        ),
        key=lambda entry: len(entry[2]),
        reverse=True,
    )
)

UNKNOWN_BINARY = "application/octet-stream"
PLAIN_TEXT = "text/plain"

#: A file below this many bytes cannot carry a real signature at all — the honest answer is
#: "unknown," not a false match against a truncated prefix.
_MIN_BYTES_FOR_DETECTION = 2


def detect(content: bytes) -> DetectedFileType:
    """The real, verified type of `content`, from its own bytes.

    Falls through to a plain-text heuristic and then to `UNKNOWN_BINARY` — both are honest
    answers, not errors. Detecting "this is not a format we recognise" is exactly as valid an
    outcome as detecting a known one; `pipeline.py` still runs every other check (polyglot,
    malware scan) against unrecognised bytes rather than special-casing them.
    """
    if len(content) < _MIN_BYTES_FOR_DETECTION:
        return DetectedFileType(mime_type=UNKNOWN_BINARY)

    webp = _detect_webp(content)
    if webp is not None:
        return webp

    for mime_type, offset, signature in _ALL_SIGNATURES:
        end = offset + len(signature)
        if len(content) >= end and content[offset:end] == signature:
            return DetectedFileType(mime_type=mime_type, matched_signature=signature.hex())

    if _looks_like_text(content):
        return DetectedFileType(mime_type=PLAIN_TEXT)
    return DetectedFileType(mime_type=UNKNOWN_BINARY)


def _detect_webp(content: bytes) -> DetectedFileType | None:
    """RIFF at offset 0 *and* WEBP at offset 8, both required — the two-anchor check
    described in this module's own signature-table docstring."""
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        # The real 12-byte header, hex-encoded like every other signature here — not a
        # synthetic placeholder — so a consumer computing "how many header bytes does this
        # match represent" (`polyglot_detection.check`) gets a real, decodable answer.
        return DetectedFileType(mime_type="image/webp", matched_signature=content[0:12].hex())
    return None


def _looks_like_text(content: bytes) -> bool:
    """A cheap, real heuristic: no NUL bytes and the sample decodes as UTF-8.

    Not a format verification — there is no magic-byte signature for "plain text" to check
    against — but a legitimate CSV/receipt-text upload should not be forced into
    `application/octet-stream` just because no binary signature matched.
    """
    sample = content[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


__all__ = ["MAGIC_SIGNATURES", "PLAIN_TEXT", "UNKNOWN_BINARY", "detect"]
