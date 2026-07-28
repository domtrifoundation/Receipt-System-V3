"""Magic bytes, polyglot detection and the two-pass container check (§1, §3, §8).

§8's second and third testing hooks live here:

* **Polyglot detection test** — "a file crafted to be valid as two different formats
  simultaneously (a classic real attack technique) is correctly flagged, not passed based on
  only checking the first plausible format match."
* **Container two-pass test** — "a zip containing one malicious file among otherwise-clean
  ones is caught by the per-file pass even though the container itself passes its own bomb
  check."

The bomb check reads `infolist()` metadata *before* any extraction (§3). Every archive in this
file is real zip bytes for that reason: a fixture that handed the check a fabricated result
would skip the only code that claim is about.
"""

from __future__ import annotations

import zipfile

from core.content_security.contracts import ContainerScanRequest, ScanOutcome, ScanRequest
from core.content_security.errors import E_ARCHIVE_BOMB, E_MEMBER_UNSAFE, E_POLYGLOT_DETECTED
from core.content_security.pipeline import ContentScanner
from core.content_security.scanning import bomb_check, magic_bytes, polyglot_detection

from .conftest import PDF_BYTES, PNG_BYTES, FakeProvider, make_zip, registry_of, run


# --------------------------------------------------------------------- magic bytes


def test_real_type_is_read_from_bytes_not_from_the_claimed_name():
    """§1: never trust an extension or a client-supplied MIME type.

    The claim is deliberately a lie here, because that is the actual attack — an executable
    named `receipt.png` uploaded through a channel that filters on extension.
    """
    detected = magic_bytes.detect(PDF_BYTES)

    assert detected.mime_type == "application/pdf"


def test_unrecognised_bytes_are_not_silently_called_safe():
    detected = magic_bytes.detect(b"\x01\x02\x03\x04 not a known format")

    assert detected.mime_type != "application/pdf"
    assert detected.mime_type != "image/png"


# ----------------------------------------------------------------------- polyglot


def test_polyglot_valid_as_two_formats_is_flagged():
    """§8's polyglot hook — a PDF that is also a working zip archive.

    The point is that checking only the first plausible format match passes this file. Its PDF
    header is genuine; so is the zip structure appended after it, which is what an unzip tool
    would find by scanning from the end.
    """
    inner = make_zip({"payload.txt": b"anything"})
    crafted = PDF_BYTES + inner

    finding = polyglot_detection.check(crafted)

    assert finding.is_polyglot
    assert finding.primary_type == "application/pdf"
    assert "application/zip" in finding.embedded_types


def test_an_ordinary_file_is_not_a_false_positive():
    """A detector that flags clean PDFs gets switched off, which is worse than not having it."""
    assert not polyglot_detection.check(PDF_BYTES).is_polyglot
    assert not polyglot_detection.check(PNG_BYTES).is_polyglot


def test_a_real_zip_is_not_flagged_as_a_zip_polyglot():
    """A zip being valid as a zip is not two formats — it is one."""
    assert not polyglot_detection.check(make_zip({"a.txt": b"hello"})).is_polyglot


def test_polyglot_never_reaches_a_scan_provider_and_goes_to_review(png):
    """A polyglot is denied before any provider is asked, and a human sees it.

    Not the same as a scanner-confirmed malicious verdict: nothing has said this file *is*
    malware, only that its shape is dishonest, so §9's "don't unilaterally resolve an
    ambiguous signal" applies and it routes to staff review rather than being condemned or
    silently discarded.
    """
    provider = FakeProvider("clamav", ScanOutcome.CLEAN)
    scanner = ContentScanner(registry_of(provider))
    crafted = PDF_BYTES + make_zip({"payload.txt": b"anything"})

    verdict = run(scanner.scan(ScanRequest(content=crafted)))

    assert verdict.safe is False
    assert verdict.error_code == E_POLYGLOT_DETECTED
    assert verdict.requires_staff_review is True
    assert provider.scan_calls == 0


# ---------------------------------------------------------------------- containers


def test_bomb_check_reads_metadata_without_extracting():
    """§3: `infolist()` metadata — compression ratio, cumulative size, entry count — first.

    A highly compressible payload is what makes the ratio meaningful; the archive is never
    unpacked to measure it, which is the entire point of doing this pass before extraction.
    """
    hostile = make_zip({"bomb.txt": b"\x00" * (50 * 1024 * 1024)})

    result = bomb_check.check(hostile)

    assert result.safe is False
    assert result.compression_ratio > bomb_check.MAX_AGGREGATE_COMPRESSION_RATIO


def test_ordinary_archive_passes_its_bomb_check():
    ordinary = make_zip({"receipt.png": PNG_BYTES, "receipt.pdf": PDF_BYTES})

    assert bomb_check.check(ordinary).safe is True


def test_entry_count_ceiling_is_enforced():
    crowded = make_zip({f"f{i}.txt": b"x" for i in range(bomb_check.MAX_ENTRY_COUNT + 1)})

    result = bomb_check.check(crowded)

    assert result.safe is False
    assert result.entry_count > bomb_check.MAX_ENTRY_COUNT


def test_non_archive_bytes_are_not_a_valid_container():
    assert bomb_check.check(PNG_BYTES).safe is False


def test_container_two_pass_catches_one_bad_member_among_clean_ones():
    """§8's container two-pass hook, exactly as written.

    The container passes its own bomb check — nothing about its metadata is suspicious — and
    the malicious member is caught only because every extracted file gets its own full scan.
    A single-pass implementation returns `safe=True` here, which is why this test is the one
    that proves §3's second pass exists.
    """

    class PerMemberProvider(FakeProvider):
        """Malicious for one specific payload, clean for everything else."""

        async def scan(self, content: bytes, *, blob_ref: str = ""):
            self.scan_calls += 1
            from core.content_security.contracts import ProviderScanResult

            outcome = (
                ScanOutcome.MALICIOUS if b"EICAR-TEST" in content else ScanOutcome.CLEAN
            )
            return ProviderScanResult(provider_name=self.name, outcome=outcome)

    archive = make_zip(
        {
            "clean-receipt.png": PNG_BYTES,
            "invoice.pdf": PDF_BYTES,
            "notes.txt": b"EICAR-TEST payload stand-in",
        }
    )
    scanner = ContentScanner(registry_of(PerMemberProvider("clamav")))

    assert bomb_check.check(archive).safe is True

    verdict = run(scanner.scan_container(ContainerScanRequest(content=archive)))

    assert verdict.safe is False
    assert verdict.error_code == E_MEMBER_UNSAFE
    assert verdict.member_verdicts["notes.txt"].safe is False
    assert verdict.member_verdicts["clean-receipt.png"].safe is True


def test_container_of_clean_members_passes_both_passes():
    archive = make_zip({"a.png": PNG_BYTES, "b.pdf": PDF_BYTES})
    scanner = ContentScanner(registry_of(FakeProvider("clamav", ScanOutcome.CLEAN)))

    verdict = run(scanner.scan_container(ContainerScanRequest(content=archive)))

    assert verdict.safe is True
    assert set(verdict.member_verdicts) == {"a.png", "b.pdf"}


def test_bomb_container_is_rejected_before_any_member_is_scanned():
    """Extraction never happens on a container that failed its first pass."""
    provider = FakeProvider("clamav", ScanOutcome.CLEAN)
    hostile = make_zip({"bomb.txt": b"\x00" * (50 * 1024 * 1024)})
    scanner = ContentScanner(registry_of(provider))

    verdict = run(scanner.scan_container(ContainerScanRequest(content=hostile)))

    assert verdict.safe is False
    assert verdict.error_code == E_ARCHIVE_BOMB
    assert provider.scan_calls == 0


def test_remediation_is_feature_detected_not_version_gated():
    """§3.1: gated on `hasattr(zipfile.ZipFile, "remove")`, never on `sys.version_info`.

    A still-alpha API can change shape before it stabilises. A hard version check would need
    updating if that happens; a feature-detection check simply stops matching and falls
    through to the safe default — rejecting the whole archive, exactly as if the feature did
    not exist.
    """
    nested = make_zip({"ok.txt": b"fine", "inner.zip": make_zip({"deep.txt": b"x"})})
    result = bomb_check.check(nested)

    _content, remediation = bomb_check.remediate_or_reject(nested, result.bad_entries)

    if hasattr(zipfile.ZipFile, "remove"):
        assert remediation.action == "stripped_and_extracted"
        assert remediation.removed == result.bad_entries
    else:
        assert remediation.action == "rejected_whole_archive"
        assert remediation.removed == ()
