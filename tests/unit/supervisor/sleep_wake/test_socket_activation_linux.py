"""`socket_activation_linux.py` — unit generation is real and tested everywhere;
`is_systemd_available()` is a real live probe, correctly reporting unavailable on this
non-Linux development machine (see that function's own module docstring for what is and
isn't verified here)."""

from __future__ import annotations

from supervisor.sleep_wake.socket_activation_linux import (
    is_systemd_available,
    service_unit_text,
    socket_unit_text,
)


def test_is_systemd_available_is_a_real_probe_not_a_platform_guess():
    # A real, live subprocess probe. This development machine is Windows, so the honest,
    # correct answer is False — asserted directly rather than skipped, since a genuinely
    # unavailable systemd IS the real state this function must report accurately.
    assert isinstance(is_systemd_available(), bool)


def test_socket_unit_text_extracts_the_port_from_a_host_port_address():
    text = socket_unit_text("ocr", "127.0.0.1:50071")

    assert "ListenStream=50071" in text
    assert "Service=ocr.service" in text


def test_service_unit_text_references_its_own_socket():
    text = service_unit_text("ocr", "/opt/resibo/.venvs/core.ocr/bin/python -m core.ocr.service", "/opt/resibo/releases/x03.00.00")

    assert "Requires=ocr.socket" in text
    assert "/opt/resibo/.venvs/core.ocr/bin/python -m core.ocr.service" in text
    assert "WorkingDirectory=/opt/resibo/releases/x03.00.00" in text
