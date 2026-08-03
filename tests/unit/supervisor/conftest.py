"""Shared fixtures for Supervisor's unit tests.

`geo_address_spec` is a real, launchable `ServiceSpec` against this repo's own already-
built `core/geo_address/service.py` — Boot Sequence tests launch a genuine subprocess and
health-gate it over a real socket, never a mocked process.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket

import pytest

from supervisor.contracts import ServiceSpec


def run(coro):
    return asyncio.run(coro)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def geo_address_spec() -> ServiceSpec:
    return ServiceSpec(
        name="geo_address", import_path="core.geo_address", serve_module="core.geo_address.service",
        address=f"127.0.0.1:{free_port()}",
    )


@pytest.fixture
def killer():
    """Tracks launched PIDs across a test and force-kills them at teardown — real
    subprocesses need real cleanup, never left running past their own test."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def pid_listening_on(port: int) -> int | None:
    """A real, portable-enough "who is holding this port" lookup for test teardown —
    used when a test can't otherwise learn the pid a launched service actually got
    (`ForceWake`'s own RPC response carries no pid, matching `supervisor.proto`'s own §8
    sketch)."""
    import subprocess

    if os.name == "nt":
        result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=False)
        for line in result.stdout.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        return int(parts[-1])
                    except ValueError:
                        continue
        return None

    result = subprocess.run(["lsof", "-t", f"-i:{port}"], capture_output=True, text=True, check=False)
    text = result.stdout.strip()
    return int(text.splitlines()[0]) if text else None
