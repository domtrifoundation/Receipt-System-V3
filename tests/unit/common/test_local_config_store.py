from __future__ import annotations

from pathlib import Path

from common.local_config_store import LocalConfigStore


def test_get_on_a_fresh_store_returns_the_default(tmp_path: Path):
    store = LocalConfigStore(tmp_path, "auth/config.json")

    assert store.get("tenancy_mode") is None
    assert store.get("tenancy_mode", "multi") == "multi"


def test_set_and_get_round_trip(tmp_path: Path):
    store = LocalConfigStore(tmp_path, "auth/config.json")

    store.set("tenancy_mode", "single")

    assert store.get("tenancy_mode") == "single"


def test_multiple_keys_coexist_in_one_file(tmp_path: Path):
    store = LocalConfigStore(tmp_path, "auth/config.json")

    store.set("tenancy_mode", "single")
    store.set("public_facing", True)

    assert store.get_all() == {"tenancy_mode": "single", "public_facing": True}


def test_state_persists_across_a_new_store_instance(tmp_path: Path):
    LocalConfigStore(tmp_path, "auth/config.json").set("tenancy_mode", "single")

    reopened = LocalConfigStore(tmp_path, "auth/config.json")

    assert reopened.get("tenancy_mode") == "single"


def test_two_different_relpaths_never_share_state(tmp_path: Path):
    LocalConfigStore(tmp_path, "auth/config.json").set("mode", "single")
    telemetrees_store = LocalConfigStore(tmp_path, "telemetrees/config.json")

    assert telemetrees_store.get("mode") is None
