"""`VersionPinStore` — §5.2's own surgical per-service, per-channel override."""

from __future__ import annotations

from pathlib import Path

from supervisor.version_pins import VersionPinStore


def test_get_pin_on_a_fresh_store_returns_none(tmp_path: Path):
    store = VersionPinStore(tmp_path)

    assert store.get_pin("beta", "ocr") is None


def test_set_pin_and_get_pin_round_trip(tmp_path: Path):
    store = VersionPinStore(tmp_path)

    pin = store.set_pin("beta", "ocr", "x03.01.05", pinned_by="owner-1")

    assert pin.channel == "beta"
    assert pin.service_name == "ocr"
    assert pin.pinned_version == "x03.01.05"
    assert store.get_pin("beta", "ocr") == pin


def test_a_pin_on_one_service_never_affects_another_on_the_same_channel(tmp_path: Path):
    """§7's own named testing hook: "confirms PinServiceVersion on one service within a
    channel doesn't affect any other service on that same channel"."""
    store = VersionPinStore(tmp_path)

    store.set_pin("beta", "ocr", "x03.01.05", pinned_by="owner-1")

    assert store.get_pin("beta", "inference") is None
    assert store.get_pin("beta", "preprocessing") is None


def test_a_pin_on_one_channel_never_affects_the_same_service_on_another_channel(tmp_path: Path):
    store = VersionPinStore(tmp_path)

    store.set_pin("beta", "ocr", "x03.01.05", pinned_by="owner-1")

    assert store.get_pin("stable", "ocr") is None


def test_setting_pinned_version_none_clears_an_existing_pin(tmp_path: Path):
    store = VersionPinStore(tmp_path)
    store.set_pin("beta", "ocr", "x03.01.05", pinned_by="owner-1")

    cleared = store.set_pin("beta", "ocr", None, pinned_by="owner-1")

    assert cleared is None
    assert store.get_pin("beta", "ocr") is None


def test_list_pins_filters_by_channel(tmp_path: Path):
    store = VersionPinStore(tmp_path)
    store.set_pin("beta", "ocr", "x03.01.05", pinned_by="owner-1")
    store.set_pin("stable", "inference", "x03.00.09", pinned_by="owner-1")

    beta_pins = store.list_pins("beta")

    assert [p.service_name for p in beta_pins] == ["ocr"]


def test_list_pins_with_no_channel_returns_every_active_pin(tmp_path: Path):
    store = VersionPinStore(tmp_path)
    store.set_pin("beta", "ocr", "x03.01.05", pinned_by="owner-1")
    store.set_pin("stable", "inference", "x03.00.09", pinned_by="owner-1")

    all_pins = store.list_pins()

    assert len(all_pins) == 2


def test_state_persists_across_a_new_store_instance(tmp_path: Path):
    VersionPinStore(tmp_path).set_pin("beta", "ocr", "x03.01.05", pinned_by="owner-1")

    reopened = VersionPinStore(tmp_path)

    assert reopened.get_pin("beta", "ocr").pinned_version == "x03.01.05"
