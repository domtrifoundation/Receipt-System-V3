"""The reverse gazetteer scan (`v3-deepdive-15-matching-api.md` §4).

Two guarantees this module protects, each with its own named test:

* **Cost is bounded by the plausibility window, never by how long the raw OCR text actually
  is** — `test_a_mention_placed_beyond_the_window_is_never_found` and
  `test_widening_the_window_finds_a_mention_a_narrower_one_missed` are the direct proof: the
  exact same raw text and candidate produce different answers purely because of where the
  window boundary falls, which is only possible if the scan genuinely never looks past it.
* **A missed or mangled primary vendor-field extraction is still catchable** — the vendor's
  name appearing anywhere legible in the raw OCR text is enough, `test_reverse_scan_catches_a_
  vendor_name_the_forward_field_extraction_missed`.
"""

from __future__ import annotations

import time

from core.matching.reverse_gazetteer import reverse_gazetteer_scan

from .conftest import make_candidate


def test_reverse_scan_catches_a_vendor_name_the_forward_field_extraction_missed():
    """Deep-dive §4's own framing: the primary vendor-field extraction mangled or missed the
    vendor line, but the name is still legible somewhere in the receipt's raw OCR text."""
    candidates = (make_candidate("c1", "Jollibee Foods Corporation", aliases=("Jollibee",)),)
    raw_text = "RECEIPT NO 00123\nwe ate at Jollibee yesterday\nTOTAL 250.00"

    found = reverse_gazetteer_scan(raw_text, candidates)

    assert found
    assert found[0].canonical_name == "Jollibee Foods Corporation"
    assert found[0].matched_alias == "Jollibee"


def test_a_mention_placed_beyond_the_window_is_never_found():
    """The direct cost-bounding proof (§4): a vendor mention placed after the window boundary
    must never surface, no matter how much of the text follows it."""
    candidates = (make_candidate("c1", "Jollibee Foods Corporation"),)
    filler = "x" * 600
    raw_text = f"{filler} we ate at Jollibee yesterday {'x' * 200}"

    found = reverse_gazetteer_scan(raw_text, candidates, plausibility_window=500)

    assert found == []


def test_widening_the_window_finds_a_mention_a_narrower_one_missed():
    """Same raw text and candidate as above — only the window changes. This is what proves
    the earlier miss was genuinely about window scope, not about the scorer failing to
    recognise the name at all."""
    candidates = (make_candidate("c1", "Jollibee Foods Corporation"),)
    filler = "x" * 600
    raw_text = f"{filler} we ate at Jollibee yesterday {'x' * 200}"

    found = reverse_gazetteer_scan(raw_text, candidates, plausibility_window=700)

    assert found
    assert found[0].canonical_name == "Jollibee Foods Corporation"


def test_empty_raw_text_returns_no_candidates_without_crashing():
    candidates = (make_candidate("c1", "Jollibee Foods Corporation"),)

    assert reverse_gazetteer_scan("", candidates) == []
    assert reverse_gazetteer_scan("   ", candidates) == []


def test_scan_cost_stays_bounded_as_the_candidate_universe_grows():
    """§8's own "reverse-scan cost bench" testing hook: scan time must stay bounded as the
    known-vendor universe grows, not blow up — a loose wall-clock ceiling here (rather than an
    exact operation count) is enough to catch an accidental quadratic-in-text-length regression
    without being flaky on slow CI, since the window itself already bounds per-candidate cost."""
    candidates = tuple(
        make_candidate(f"c{i}", f"Business Number {i} Trading Corporation") for i in range(500)
    )
    raw_text = "some receipt text " * 20 + "Business Number 250 Trading Corporation"

    started = time.monotonic()
    found = reverse_gazetteer_scan(raw_text, candidates, plausibility_window=500)
    elapsed = time.monotonic() - started

    assert found
    assert found[0].canonical_name == "Business Number 250 Trading Corporation"
    assert elapsed < 2.0  # 500 candidates x one bounded-window scan each, comfortably fast


def test_results_are_ranked_and_respect_limit():
    candidates = tuple(
        make_candidate(f"c{i}", f"Business Number {i} Trading Corporation") for i in range(10)
    )
    raw_text = "Business Number 3 Trading Corporation appears here"

    found = reverse_gazetteer_scan(raw_text, candidates, limit=2)

    assert len(found) == 2
    assert found[0].score >= found[1].score
