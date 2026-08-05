"""§6.3's own Linux wake mechanism — "systemd socket activation (confirmed current,
standard, actively used — Docker itself runs this way) is the real, off-the-shelf
mechanism: a lightweight `.socket` unit listens on a sleeping service's gRPC port;
systemd itself holds the socket while the actual service process isn't running at all;
the first incoming connection triggers systemd to start the service and hand it the
socket. Genuinely free — no custom code needed for the activation mechanism itself."

**Unverified on real systemd — this development machine is Windows.** What is real and
tested here: the unit-file generation (`socket_unit_text()`/`service_unit_text()`), which
is pure string formatting checkable without a Linux host at all, and `is_systemd_available()`,
a real subprocess probe that correctly reports unavailable on this dev machine (confirmed
live). What is **not** verified: the actual runtime hand-off behaviour under a real
`systemd` — whether this project's own `grpc.aio.server()` processes correctly accept a
passed-in listening socket via `SD_LISTEN_FDS_START`-style handling, or whether the
simpler `systemd-socket-proxyd` fallback (decoupling the socket lifecycle from the
service entirely, so the service needs no special support at all) is the one actually
wired in for a real deployment. Flagged honestly rather than assumed working.
"""

from __future__ import annotations

import shutil
import subprocess

__all__ = ["is_systemd_available", "service_unit_text", "socket_unit_text"]


def is_systemd_available() -> bool:
    """A real, live probe — `systemctl` on `PATH` and responsive. Never assumed from the
    platform name alone (a container or minimal Linux image may have no systemd at all)."""
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return False
    try:
        result = subprocess.run([systemctl, "--version"], capture_output=True, timeout=5.0, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def socket_unit_text(service_name: str, listen_address: str) -> str:
    """The `.socket` unit content for `service_name` — systemd itself holds
    `listen_address` while the real service is not running, per the module docstring.
    `listen_address` is `host:port`; systemd's own `ListenStream=` directive wants just
    the port for a wildcard/localhost bind, which is what every service this project
    launches actually uses.
    """
    _, _, port = listen_address.rpartition(":")
    return (
        f"[Unit]\n"
        f"Description=Resibo {service_name} socket (Supervisor-managed, sleep/wake)\n\n"
        f"[Socket]\n"
        f"ListenStream={port}\n"
        f"Service={service_name}.service\n\n"
        f"[Install]\n"
        f"WantedBy=sockets.target\n"
    )


def service_unit_text(service_name: str, exec_start: str, working_directory: str) -> str:
    """The paired `.service` unit — `Requires=`/socket-activated, never started
    directly by systemd's own timers (that is `sleep_wake`'s own schedule table, §6.4,
    not this file's concern)."""
    return (
        f"[Unit]\n"
        f"Description=Resibo {service_name} (Supervisor-managed, sleep/wake)\n"
        f"Requires={service_name}.socket\n\n"
        f"[Service]\n"
        f"Type=simple\n"
        f"WorkingDirectory={working_directory}\n"
        f"ExecStart={exec_start}\n"
    )
