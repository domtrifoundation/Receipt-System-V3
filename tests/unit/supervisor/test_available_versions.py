"""`AvailableVersionsStore` — the real "which versions may run concurrently" record, and
its structural single-instance enforcement for `interface_tui`/`inference`."""

from __future__ import annotations

from pathlib import Path

from supervisor.available_versions import AvailableVersionsStore, is_single_instance


def test_get_available_on_a_fresh_store_returns_empty(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)

    assert store.get_available("beta", "ocr") == ()


def test_set_available_and_get_available_round_trip(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)

    stored = store.set_available("beta", "ocr", ("x03.01.05", "x03.01.06"))

    assert stored == ("x03.01.05", "x03.01.06")
    assert store.get_available("beta", "ocr") == ("x03.01.05", "x03.01.06")


def test_set_available_dedupes_while_preserving_order(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)

    stored = store.set_available("beta", "ocr", ("x03.01.05", "x03.01.06", "x03.01.05"))

    assert stored == ("x03.01.05", "x03.01.06")


def test_single_instance_services_are_truncated_to_the_last_version(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)

    stored = store.set_available("beta", "interface_tui", ("x03.01.05", "x03.01.06", "x03.01.07"))

    assert stored == ("x03.01.07",)
    assert store.get_available("beta", "interface_tui") == ("x03.01.07",)


def test_inference_is_also_single_instance(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)

    stored = store.set_available("beta", "inference", ("x03.01.05", "x03.01.06"))

    assert stored == ("x03.01.06",)


def test_regular_services_are_not_single_instance():
    assert is_single_instance("interface_tui") is True
    assert is_single_instance("inference") is True
    assert is_single_instance("ocr") is False


def test_setting_an_empty_tuple_clears_an_existing_entry(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)
    store.set_available("beta", "ocr", ("x03.01.05",))

    cleared = store.set_available("beta", "ocr", ())

    assert cleared == ()
    assert store.get_available("beta", "ocr") == ()


def test_available_versions_on_one_service_never_affect_another(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)

    store.set_available("beta", "ocr", ("x03.01.05",))

    assert store.get_available("beta", "inference") == ()


def test_available_versions_on_one_channel_never_affect_another_channel(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)

    store.set_available("beta", "ocr", ("x03.01.05",))

    assert store.get_available("stable", "ocr") == ()


def test_list_all_filters_by_channel(tmp_path: Path):
    store = AvailableVersionsStore(tmp_path)
    store.set_available("beta", "ocr", ("x03.01.05",))
    store.set_available("stable", "preprocessing", ("x03.00.09",))

    beta_only = store.list_all("beta")

    assert beta_only == {"ocr": ("x03.01.05",)}


def test_state_persists_across_a_new_store_instance(tmp_path: Path):
    AvailableVersionsStore(tmp_path).set_available("beta", "ocr", ("x03.01.05",))

    reopened = AvailableVersionsStore(tmp_path)

    assert reopened.get_available("beta", "ocr") == ("x03.01.05",)
