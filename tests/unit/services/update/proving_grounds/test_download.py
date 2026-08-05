"""`download.py` — real streamed downloads against a real local HTTP server, matching
`test_keymaster_client.py`'s own "real socket, not a mocked transport" discipline."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from services.update.proving_grounds.download import download_file


def run(coro):
    return asyncio.run(coro)


class _Handler(BaseHTTPRequestHandler):
    response_body: bytes = b"hello world"
    last_auth_header: str | None = None

    def do_GET(self):  # noqa: N802 - stdlib's own naming
        type(self).last_auth_header = self.headers.get("Authorization")
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).response_body)))
        self.end_headers()
        self.wfile.write(type(self).response_body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib's own signature
        pass


@pytest.fixture
def server():
    _Handler.response_body = b"hello world"
    _Handler.last_auth_header = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    thread.join(timeout=5)


def test_download_file_writes_real_bytes(server, tmp_path: Path):
    port = server.server_address[1]
    destination = tmp_path / "out.bin"

    result = run(download_file(f"http://127.0.0.1:{port}/file", destination))

    assert result.ok is True
    assert result.bytes_written == len(b"hello world")
    assert destination.read_bytes() == b"hello world"


def test_download_file_sends_hf_bearer_token(server, tmp_path: Path):
    port = server.server_address[1]

    run(download_file(f"http://127.0.0.1:{port}/file", tmp_path / "out.bin", hf_token="secret-token"))

    assert _Handler.last_auth_header == "Bearer secret-token"


def test_download_file_omits_auth_header_when_no_token_given(server, tmp_path: Path):
    port = server.server_address[1]

    run(download_file(f"http://127.0.0.1:{port}/file", tmp_path / "out.bin"))

    assert _Handler.last_auth_header is None


def test_download_file_reports_a_real_error_for_an_unreachable_host(tmp_path: Path):
    result = run(download_file("http://127.0.0.1:1/nope", tmp_path / "out.bin", timeout_seconds=2.0))

    assert result.ok is False
    assert result.error_code == "DOWNLOAD_FAILED"
