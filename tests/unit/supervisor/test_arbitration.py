"""`ChannelArbitrator` — §3.1's own "small local record" of which release is active per
channel, persisted as one small JSON file."""

from __future__ import annotations

from pathlib import Path

from supervisor.arbitration import ChannelArbitrator
from supervisor.errors import UnknownChannel

import pytest


def test_get_active_on_a_fresh_install_returns_none(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)

    assert arb.get_active("stable") is None


def test_require_active_raises_for_an_unknown_channel(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)

    with pytest.raises(UnknownChannel):
        arb.require_active("stable")


def test_set_active_and_get_active_round_trip(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)
    release_dir = tmp_path / "releases" / "x03.00.00_abc123"

    result = arb.set_active("stable", release_dir)
    active = arb.get_active("stable")

    assert active.channel == "stable"
    assert active.release_dir == release_dir
    assert active == result


def test_prior_release_is_none_before_a_second_cutover(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)
    arb.set_active("stable", tmp_path / "releases" / "v1")

    assert arb.prior_release("stable") is None


def test_prior_release_tracks_the_previous_activation(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)
    arb.set_active("stable", tmp_path / "releases" / "v1")
    arb.set_active("stable", tmp_path / "releases" / "v2")

    assert arb.prior_release("stable") == tmp_path / "releases" / "v1"
    assert arb.get_active("stable").release_dir == tmp_path / "releases" / "v2"


def test_channels_are_independent(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)
    arb.set_active("stable", tmp_path / "releases" / "stable-v1")
    arb.set_active("beta", tmp_path / "releases" / "beta-v1")

    assert arb.get_active("stable").release_dir != arb.get_active("beta").release_dir
    assert {r.channel for r in arb.all_active()} == {"stable", "beta"}


def test_state_persists_across_a_new_arbitrator_instance(tmp_path: Path):
    ChannelArbitrator(tmp_path).set_active("stable", tmp_path / "releases" / "v1")

    reopened = ChannelArbitrator(tmp_path)

    assert reopened.get_active("stable").release_dir == tmp_path / "releases" / "v1"
