"""The reverse-check phase in isolation (`v3-deepdive-16-geo-address-api.md` §1).

`corroboration.py`'s own tests already exercise this end-to-end; these tests pin down the
module's own edge cases directly — no coordinates, no hint, every provider failing — so a
future change to `corroboration.py`'s own orchestration cannot silently stop testing them.
"""

from __future__ import annotations

import pytest

from core.geo_address.reverse_check import reverse_check

from .conftest import FakeProvider, make_address, run

WITH_COORDS = make_address("123 Rizal Ave, Manila", lat=14.5995, lon=120.9842)
NO_COORDS = make_address("somewhere, Manila", lat=None, lon=None)


def test_skips_entirely_without_coordinates():
    provider = FakeProvider("locationiq", reverse_name="Should Not Be Called")

    name, discrepancy, results = run(reverse_check(NO_COORDS, "Sari-Sari Store", (provider,)))

    assert name == ""
    assert not discrepancy
    assert results == ()
    assert provider.reverse_calls == []


def test_skips_entirely_without_a_vendor_hint():
    provider = FakeProvider("locationiq", reverse_name="Whatever Corp")

    name, discrepancy, results = run(reverse_check(WITH_COORDS, "", (provider,)))

    assert name == ""
    assert not discrepancy
    assert provider.reverse_calls == []


def test_skips_providers_that_are_unavailable():
    down = FakeProvider("locationiq", available=False, reverse_name="Ignored")

    name, discrepancy, results = run(reverse_check(WITH_COORDS, "Sari-Sari Store", (down,)))

    assert name == ""
    assert down.reverse_calls == []


def test_every_provider_failing_the_reverse_call_degrades_to_no_signal():
    """§4.4 applied to the reverse-check pass specifically: a provider that cannot answer the
    reverse lookup must not turn into a false "no discrepancy" or a crash — it is simply
    silent on this question."""
    failing = FakeProvider("locationiq", reverse_fails=True)

    name, discrepancy, results = run(reverse_check(WITH_COORDS, "Sari-Sari Store", (failing,)))

    assert name == ""
    assert not discrepancy
    assert results == ()


def test_flags_a_real_discrepancy():
    provider = FakeProvider("locationiq", reverse_name="Completely Unrelated Business")

    name, discrepancy, _ = run(reverse_check(WITH_COORDS, "Sari-Sari Store", (provider,)))

    assert name == "Completely Unrelated Business"
    assert discrepancy


def test_does_not_flag_a_close_match():
    provider = FakeProvider("locationiq", reverse_name="Sari Sari Store")  # minor OCR variance

    name, discrepancy, _ = run(reverse_check(WITH_COORDS, "Sari-Sari Store", (provider,)))

    assert not discrepancy


@pytest.mark.parametrize("hint", [" ", "\t\n"])
def test_a_whitespace_only_hint_is_treated_as_no_hint(hint):
    provider = FakeProvider("locationiq", reverse_name="Whatever Corp")

    name, discrepancy, results = run(reverse_check(WITH_COORDS, hint, (provider,)))

    assert name == ""
    assert provider.reverse_calls == []
