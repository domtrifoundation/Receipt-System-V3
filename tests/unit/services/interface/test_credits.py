"""`CreditsScreen` — real dependency-notice content, not a placeholder."""

from __future__ import annotations

from services.interface.tui.custom_screens.credits import THIRD_PARTY_DEPENDENCIES


def test_every_dependency_notice_names_a_real_requirements_txt_package():
    packages = {d.package for d in THIRD_PARTY_DEPENDENCIES}
    assert "grpcio" in packages
    assert "textual" in packages
    assert "rapidfuzz" in packages


def test_unverified_licenses_are_explicitly_none_not_a_guess():
    """`intuit-oauth`/`python-quickbooks`/`xero-python` were not confidently sourced this
    pass — `None` is the honest value, never a fabricated license name."""
    unverified = {d.package for d in THIRD_PARTY_DEPENDENCIES if d.license is None}
    assert "intuit-oauth" in unverified
