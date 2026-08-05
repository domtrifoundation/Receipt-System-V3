"""ASCII codename banners (`v3-plan-02-architecture.md`) — the real `beta.txt` asset,
not a fabricated string, and the compact header form used atop the main menu."""

from __future__ import annotations

from services.interface.tui.banners import ascii_banner, header_line


def test_pre_release_ascii_banner_reads_the_real_beta_asset():
    banner = ascii_banner("x00.00.57")

    assert banner != ""
    assert all(ord(c) < 128 for c in banner)  # true ASCII — safe on any console codepage
    assert "#" in banner  # the real block-art asset, not a placeholder


def test_header_line_names_beta_and_the_running_version():
    line = header_line("x00.00.57")

    assert line == "BETA — x00.00.57"


def test_a_major_with_no_codename_yet_falls_back_to_the_bare_version():
    line = header_line("x99.00.00")

    assert line == "x99.00.00"


def test_ascii_banner_is_empty_for_a_major_with_no_codename():
    assert ascii_banner("x99.00.00") == ""
