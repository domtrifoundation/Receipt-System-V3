"""`KeymasterClient` (`v3-deepdive-24-update-deployment-api.md` §4).

A real local HTTP server, in a background thread — not a mocked `httpx` transport. The thing
under test is this client's own request/response handling, and a real socket is what proves it
actually speaks HTTP correctly rather than merely satisfying a mock's expectations.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.update.contracts import KeymasterRejectionReason
from services.update.keymaster_client import CLONE_TOKEN_PATH, KeymasterClient


class _Handler(BaseHTTPRequestHandler):
    """Configured per-test via class attributes rather than `__init__` args — `HTTPServer`
    constructs handler instances itself, one per request, with a fixed signature."""

    response_status = 200
    response_body: bytes = b"{}"
    last_request_body: bytes | None = None
    last_request_path: str | None = None

    def do_POST(self):  # noqa: N802 - stdlib's own naming
        length = int(self.headers.get("Content-Length", 0))
        type(self).last_request_body = self.rfile.read(length)
        type(self).last_request_path = self.path
        self.send_response(type(self).response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(type(self).response_body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib's own signature
        pass  # keep test output clean; failures are asserted, not read from server logs


@pytest.fixture
def server():
    # _Handler's state is class-level (HTTPServer constructs one instance per request, with a
    # fixed signature it controls), so it must be reset per test — otherwise a later test can
    # observe a still-set `last_request_path` a prior test's own server received.
    _Handler.response_status = 200
    _Handler.response_body = b"{}"
    _Handler.last_request_body = None
    _Handler.last_request_path = None

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    thread.join(timeout=5)


def _base_url(httpd) -> str:
    host, port = httpd.server_address
    return f"http://{host}:{port}"


def run(coro):
    return asyncio.run(coro)


def test_a_valid_key_returns_a_real_token_parsed_from_the_real_response(server):
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    _Handler.response_status = 200
    _Handler.response_body = json.dumps({"token": "ghs_realtoken123", "expires_at": expires.isoformat()}).encode()

    client = KeymasterClient(_base_url(server))
    result = run(client.get_scoped_clone_token("RESIBO-AAAA-BBBB-CCCC-DDDD", "instance-1"))

    assert result.ok
    assert result.token.token == "ghs_realtoken123"
    assert result.token.expires_at == expires


def test_the_request_body_and_path_sent_to_the_real_server_match_the_documented_wire_contract(server):
    _Handler.response_status = 200
    _Handler.response_body = json.dumps(
        {"token": "x", "expires_at": datetime.now(timezone.utc).isoformat()}
    ).encode()

    client = KeymasterClient(_base_url(server))
    run(client.get_scoped_clone_token("RESIBO-KEY", "instance-42"))

    assert _Handler.last_request_path == CLONE_TOKEN_PATH
    sent = json.loads(_Handler.last_request_body)
    assert sent == {"license_key": "RESIBO-KEY", "instance_id": "instance-42"}


def test_an_empty_license_key_is_rejected_locally_without_a_network_call(server):
    """No key configured must never even attempt the request — the common, expected case for
    this repo's own current pre-release public state, not a network failure to report as one.
    """
    client = KeymasterClient(_base_url(server))
    result = run(client.get_scoped_clone_token("", "instance-1"))

    assert not result.ok
    assert result.rejection is KeymasterRejectionReason.NO_KEY_CONFIGURED
    assert _Handler.last_request_path is None


def test_a_server_rejection_never_leaks_why_the_key_failed(server):
    """§4's own constraint: every failure mode returns an identical generic rejection. This
    client's `SERVER_REJECTED` bucket is that same genericness reflected on the client side —
    the real server's response body is never even inspected for a reason once the status isn't
    200, so a differentiated body could not leak through even if a real Keymaster ever sent one.
    """
    _Handler.response_status = 403
    _Handler.response_body = b'{"error": "this text must never surface as the rejection reason"}'

    client = KeymasterClient(_base_url(server))
    result = run(client.get_scoped_clone_token("RESIBO-WRONG-KEY", "instance-1"))

    assert not result.ok
    assert result.rejection is KeymasterRejectionReason.SERVER_REJECTED


def test_a_malformed_200_response_is_reported_distinctly_not_crashed_on(server):
    _Handler.response_status = 200
    _Handler.response_body = b'{"unexpected": "shape"}'

    client = KeymasterClient(_base_url(server))
    result = run(client.get_scoped_clone_token("RESIBO-KEY", "instance-1"))

    assert not result.ok
    assert result.rejection is KeymasterRejectionReason.MALFORMED_RESPONSE


def test_an_unreachable_server_fails_open_rather_than_raising():
    """§4: "Fail-open, always — a Keymaster outage or check error never blocks the
    already-running instance." No server fixture here at all — port 1 on loopback refuses
    immediately on every platform this project targets.
    """
    client = KeymasterClient("http://127.0.0.1:1", timeout_seconds=2)
    result = run(client.get_scoped_clone_token("RESIBO-KEY", "instance-1"))

    assert not result.ok
    assert result.rejection is KeymasterRejectionReason.NETWORK_UNREACHABLE
