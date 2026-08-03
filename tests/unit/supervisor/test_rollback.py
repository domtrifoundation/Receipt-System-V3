"""`rollback_channel()` — §3.3's own revert-to-prior mechanism, confirmed live against a
real launched service."""

from __future__ import annotations

from pathlib import Path

from supervisor.arbitration import ChannelArbitrator
from supervisor.rollback import rollback_channel

from .conftest import run

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_rollback_reports_unknown_channel(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)

    result = run(rollback_channel("stable", (), arb))

    assert result.ok is False
    assert result.error_code == "UNKNOWN_CHANNEL"


def test_rollback_reports_no_prior_release(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)
    arb.set_active("stable", tmp_path / "releases" / "v1")

    result = run(rollback_channel("stable", (), arb))

    assert result.ok is False
    assert result.error_code == "NO_PRIOR_RELEASE"


def test_rollback_reports_no_prior_release_when_the_prior_dir_no_longer_exists(tmp_path: Path):
    arb = ChannelArbitrator(tmp_path)
    arb.set_active("stable", tmp_path / "releases" / "v1-gone")
    arb.set_active("stable", tmp_path / "releases" / "v2")

    result = run(rollback_channel("stable", (), arb))

    assert result.ok is False
    assert result.error_code == "NO_PRIOR_RELEASE"


def test_rollback_reverts_and_relaunches_a_real_service(tmp_path: Path, geo_address_spec, killer):
    arb = ChannelArbitrator(tmp_path)
    arb.set_active("stable", REPO_ROOT)  # "prior" — the real, launchable repo root
    arb.set_active("stable", tmp_path / "releases" / "bad-new-release")  # "current" — nothing real here

    result = run(rollback_channel("stable", (geo_address_spec,), arb, timeout_seconds=15.0))
    for s in (result.boot.services if result.boot else ()):
        if s.pid:
            killer.append(s.pid)

    assert result.ok is True
    assert result.reverted_to == REPO_ROOT
    assert arb.get_active("stable").release_dir == REPO_ROOT
