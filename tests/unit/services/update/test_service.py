"""`UpdateServicer` — the real gRPC adapter over `release_manager.py`."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

import services.update.release_manager as rm  # noqa: E402
from services.update.generated import update_pb2 as pb  # noqa: E402
from services.update.service import UpdateServicer  # noqa: E402

from .conftest import run  # noqa: E402


@pytest.fixture(autouse=True)
def _point_at_test_remote(git_remote: Path, monkeypatch):
    monkeypatch.setattr(rm, "REPO_CLONE_URL", str(git_remote))


def test_clone_release_rpc_produces_a_real_directory(tmp_path: Path):
    servicer = UpdateServicer()

    response = run(servicer.CloneRelease(pb.CloneRequest(
        install_root=str(tmp_path / "install"), channel="stable", dev_mode_set=True, dev_mode=True,
    )))

    assert response.ok is True
    assert response.error_code == ""
    assert Path(response.path).is_dir()
    assert response.version == "x00.99.00"
    assert response.finalize_ok is True


def test_clone_release_rpc_rejects_an_unknown_channel(tmp_path: Path):
    servicer = UpdateServicer()

    response = run(servicer.CloneRelease(pb.CloneRequest(
        install_root=str(tmp_path / "install"), channel="not_a_real_channel",
    )))

    assert response.ok is False
    assert response.error_code == "UNKNOWN_CHANNEL"


def test_get_active_channels_rpc_reflects_a_real_clone(tmp_path: Path):
    servicer = UpdateServicer()
    install_root = str(tmp_path / "install")
    run(servicer.CloneRelease(pb.CloneRequest(install_root=install_root, channel="stable", dev_mode_set=True, dev_mode=True)))

    response = run(servicer.GetActiveChannels(pb.ChannelRequest(install_root=install_root)))

    assert len(response.channels) == 1
    assert response.channels[0].channel == "stable"


def test_get_active_channels_rpc_on_a_fresh_install_returns_empty(tmp_path: Path):
    servicer = UpdateServicer()

    response = run(servicer.GetActiveChannels(pb.ChannelRequest(install_root=str(tmp_path / "install"))))

    assert list(response.channels) == []
