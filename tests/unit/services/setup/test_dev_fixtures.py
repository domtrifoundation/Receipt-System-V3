"""`setup-dev`'s own default-environment seeding (`v3-deepdive-11-setup-api.md` §4.1).

The central constraint this module operates under is not a design choice, it is a standing
project rule: no synthetic receipt data, ever. These tests pin that this module respects it —
`real_receipts_fixture_status` only ever reads, never writes into the fixtures directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from services.setup.dev_fixtures import (
    DEV_DEFAULT_CONFIG,
    REAL_RECEIPTS_FIXTURE_DIRNAME,
    real_receipts_fixture_status,
    seed_dev_environment,
)


def test_seeding_writes_a_structurally_complete_config(tmp_path):
    report = seed_dev_environment(tmp_path)

    assert report.written is True
    assert report.config_path.exists()
    on_disk = json.loads(report.config_path.read_text(encoding="utf-8"))
    assert on_disk == DEV_DEFAULT_CONFIG


def test_no_seeded_config_ever_contains_a_real_looking_credential():
    """Every credential-shaped field must be empty — "structurally complete so nothing crashes
    on a missing key," never a plausible-looking fake secret that could be mistaken for real.
    A direct tree walk, not a string scan, so this cannot be fooled by formatting.
    """

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"api_key", "access_key_id", "secret_access_key"}:
                    assert value == "", f"{key} must be seeded empty, got {value!r}"
                if key == "credentials":
                    assert value == {}, f"credentials must be seeded empty, got {value!r}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(DEV_DEFAULT_CONFIG)


def test_seeding_is_idempotent_and_does_not_clobber_a_contributors_own_edits(tmp_path):
    first = seed_dev_environment(tmp_path)
    (first.config_path).write_text('{"dev_mode": false, "edited_by_contributor": true}', encoding="utf-8")

    second = seed_dev_environment(tmp_path)

    assert second.written is False
    on_disk = json.loads(second.config_path.read_text(encoding="utf-8"))
    assert on_disk == {"dev_mode": False, "edited_by_contributor": True}


def test_overwrite_true_replaces_an_existing_config():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = seed_dev_environment(root)
        first.config_path.write_text('{"edited_by_contributor": true}', encoding="utf-8")

        second = seed_dev_environment(root, overwrite=True)

        assert second.written is True
        on_disk = json.loads(second.config_path.read_text(encoding="utf-8"))
        assert on_disk == DEV_DEFAULT_CONFIG


def test_receipt_fixture_status_never_creates_the_directory(tmp_path):
    """The read-only guarantee, checked directly: calling this function must never bring the
    fixtures directory into existence.
    """
    present, count = real_receipts_fixture_status(tmp_path)

    assert present is False
    assert count == 0
    assert not (tmp_path / REAL_RECEIPTS_FIXTURE_DIRNAME).exists()


def test_receipt_fixture_status_reports_real_counts_when_a_developer_has_supplied_them(tmp_path):
    """Reports on what a developer already put there — this test supplies the fixture files
    itself, standing in for a developer's own real scans; the module under test never creates
    them.
    """
    fixture_dir = tmp_path / REAL_RECEIPTS_FIXTURE_DIRNAME
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "a_developer_supplied_scan.pdf").write_bytes(b"not a real receipt, just a test placeholder")

    present, count = real_receipts_fixture_status(tmp_path)

    assert present is True
    assert count == 1


def test_an_empty_fixtures_directory_reports_as_not_present():
    """An empty directory (e.g. left by a prior gitignore-driven checkout) must read the same as
    "no fixtures yet," not be mistaken for real content.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / REAL_RECEIPTS_FIXTURE_DIRNAME).mkdir(parents=True)
        present, count = real_receipts_fixture_status(root)

    assert present is False
    assert count == 0
