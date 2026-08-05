"""`download.py`'s resume/retry behavior — real streamed downloads against a real local
HTTP server that genuinely understands `Range`, matching `test_download.py`'s own "real
socket, not a mocked transport" discipline.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from services.update.proving_grounds.download import download_file


def run(coro):
    return asyncio.run(coro)


class _RangeAwareHandler(BaseHTTPRequestHandler):
    """A real HTTP/1.1 server that honors `Range: bytes=N-` like a real file host does."""

    response_body: bytes = b""
    request_log: list[str] = []

    def do_GET(self):  # noqa: N802 - stdlib's own naming
        type(self).request_log.append(self.headers.get("Range") or "")
        body = type(self).response_body
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            start = int(range_header.removeprefix("bytes=").rstrip("-"))
            if start > len(body):
                self.send_response(416)
                self.end_headers()
                return
            chunk = body[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib's own signature
        pass


class _IgnoresRangeHandler(BaseHTTPRequestHandler):
    """A server that always answers `200` with the full body, ignoring any `Range`
    header -- the real "server doesn't support resume" case."""

    response_body: bytes = b""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).response_body)))
        self.end_headers()
        self.wfile.write(type(self).response_body)

    def log_message(self, format, *args):  # noqa: A002
        pass


class _FlakyThenOkHandler(BaseHTTPRequestHandler):
    """Fails the first N requests outright, then serves normally -- the real transient-
    network-blip shape `download_file`'s own retry exists for."""

    response_body: bytes = b""
    fail_count: int = 0
    requests_seen: int = 0

    def do_GET(self):  # noqa: N802
        type(self).requests_seen += 1
        if type(self).requests_seen <= type(self).fail_count:
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).response_body)))
        self.end_headers()
        self.wfile.write(type(self).response_body)

    def log_message(self, format, *args):  # noqa: A002
        pass


def _start(handler_cls) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd._test_thread = thread  # type: ignore[attr-defined]
    return httpd


def _stop(httpd: ThreadingHTTPServer) -> None:
    httpd.shutdown()
    httpd._test_thread.join(timeout=5)  # type: ignore[attr-defined]


# --------------------------------------------------------------------- resume


def test_resumes_from_an_existing_partial_file_via_range(tmp_path: Path):
    _RangeAwareHandler.response_body = b"0123456789" * 100_000  # 1,000,000 bytes
    _RangeAwareHandler.request_log = []
    httpd = _start(_RangeAwareHandler)
    try:
        destination = tmp_path / "out.bin"
        partial = _RangeAwareHandler.response_body[:400_000]
        destination.write_bytes(partial)

        port = httpd.server_address[1]
        result = run(download_file(f"http://127.0.0.1:{port}/file", destination))

        assert result.ok is True
        assert result.resumed is True
        assert destination.read_bytes() == _RangeAwareHandler.response_body
        assert _RangeAwareHandler.request_log == ["bytes=400000-"]
    finally:
        _stop(httpd)


def test_full_download_with_no_partial_file_is_not_marked_resumed(tmp_path: Path):
    _RangeAwareHandler.response_body = b"hello world"
    _RangeAwareHandler.request_log = []
    httpd = _start(_RangeAwareHandler)
    try:
        port = httpd.server_address[1]
        result = run(download_file(f"http://127.0.0.1:{port}/file", tmp_path / "out.bin"))

        assert result.ok is True
        assert result.resumed is False
    finally:
        _stop(httpd)


def test_resume_false_ignores_an_existing_partial_file(tmp_path: Path):
    _RangeAwareHandler.response_body = b"0123456789" * 10
    _RangeAwareHandler.request_log = []
    httpd = _start(_RangeAwareHandler)
    try:
        destination = tmp_path / "out.bin"
        destination.write_bytes(b"stale garbage")

        port = httpd.server_address[1]
        result = run(download_file(f"http://127.0.0.1:{port}/file", destination, resume=False))

        assert result.ok is True
        assert destination.read_bytes() == _RangeAwareHandler.response_body
        assert _RangeAwareHandler.request_log == [""]
    finally:
        _stop(httpd)


def test_server_that_ignores_range_gets_a_clean_restart_not_corruption(tmp_path: Path):
    _IgnoresRangeHandler.response_body = b"the full real content"
    httpd = _start(_IgnoresRangeHandler)
    try:
        destination = tmp_path / "out.bin"
        destination.write_bytes(b"stale partial")  # would corrupt if blindly appended to

        port = httpd.server_address[1]
        result = run(download_file(f"http://127.0.0.1:{port}/file", destination))

        assert result.ok is True
        assert result.resumed is False
        assert destination.read_bytes() == _IgnoresRangeHandler.response_body
    finally:
        _stop(httpd)


def test_range_not_satisfiable_discards_the_stale_partial_and_restarts(tmp_path: Path):
    _RangeAwareHandler.response_body = b"short"
    _RangeAwareHandler.request_log = []
    httpd = _start(_RangeAwareHandler)
    try:
        destination = tmp_path / "out.bin"
        destination.write_bytes(b"this partial is already longer than the real file")

        port = httpd.server_address[1]
        result = run(download_file(f"http://127.0.0.1:{port}/file", destination))

        assert result.ok is True
        assert destination.read_bytes() == _RangeAwareHandler.response_body
    finally:
        _stop(httpd)


# --------------------------------------------------------------------- retry


def test_retries_a_transient_server_error_and_eventually_succeeds(tmp_path: Path):
    _FlakyThenOkHandler.response_body = b"real content"
    _FlakyThenOkHandler.fail_count = 1
    _FlakyThenOkHandler.requests_seen = 0
    httpd = _start(_FlakyThenOkHandler)
    try:
        port = httpd.server_address[1]
        result = run(
            download_file(
                f"http://127.0.0.1:{port}/file", tmp_path / "out.bin", retry_delay_seconds=0.01
            )
        )

        assert result.ok is True
        assert (tmp_path / "out.bin").read_bytes() == b"real content"
        assert _FlakyThenOkHandler.requests_seen == 2
    finally:
        _stop(httpd)


def test_gives_up_after_max_attempts_on_a_persistently_failing_server(tmp_path: Path):
    _FlakyThenOkHandler.response_body = b"unreachable"
    _FlakyThenOkHandler.fail_count = 99
    _FlakyThenOkHandler.requests_seen = 0
    httpd = _start(_FlakyThenOkHandler)
    try:
        port = httpd.server_address[1]
        result = run(
            download_file(
                f"http://127.0.0.1:{port}/file", tmp_path / "out.bin",
                max_attempts=2, retry_delay_seconds=0.01,
            )
        )

        assert result.ok is False
        assert _FlakyThenOkHandler.requests_seen == 2
    finally:
        _stop(httpd)
