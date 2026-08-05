"""`device_overrides.py` — real disk round-trips for manual per-preset EP selection."""

from __future__ import annotations

from pathlib import Path

from core.inference.device_overrides import (
    DEVICE_OVERRIDES_RELPATH,
    read_device_overrides,
    write_device_override,
)


def test_read_returns_empty_dict_when_nothing_was_ever_written(tmp_path: Path):
    assert read_device_overrides(tmp_path) == {}


def test_write_then_read_round_trips(tmp_path: Path):
    write_device_override(tmp_path, "phi4-mini", "cuda")

    assert read_device_overrides(tmp_path) == {"phi4-mini": "cuda"}


def test_write_creates_the_documented_relative_path(tmp_path: Path):
    write_device_override(tmp_path, "phi4-mini", "cuda")

    assert (tmp_path / DEVICE_OVERRIDES_RELPATH).is_file()


def test_setting_a_second_preset_does_not_clobber_the_first(tmp_path: Path):
    write_device_override(tmp_path, "phi4-mini", "cuda")
    write_device_override(tmp_path, "phi4-vision", "directml")

    assert read_device_overrides(tmp_path) == {"phi4-mini": "cuda", "phi4-vision": "directml"}


def test_re_setting_the_same_preset_overwrites_only_that_entry(tmp_path: Path):
    write_device_override(tmp_path, "phi4-mini", "cuda")
    write_device_override(tmp_path, "phi4-vision", "directml")
    write_device_override(tmp_path, "phi4-mini", "cpu")

    assert read_device_overrides(tmp_path) == {"phi4-mini": "cpu", "phi4-vision": "directml"}


def test_read_degrades_to_empty_on_a_corrupt_file(tmp_path: Path):
    target = tmp_path / DEVICE_OVERRIDES_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not valid json", encoding="utf-8")

    assert read_device_overrides(tmp_path) == {}


def test_read_degrades_to_empty_when_the_file_is_not_a_json_object(tmp_path: Path):
    target = tmp_path / DEVICE_OVERRIDES_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_device_overrides(tmp_path) == {}
