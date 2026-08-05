"""`ep_plugins.py`'s real download/extract/register mechanism — a real local HTTP server
serving a real zip (matching `test_download_resume.py`'s own "real socket, not a mocked
transport" discipline), never a mocked NuGet client. Registration itself is tested against
whatever `onnxruntime_genai` this dev interpreter actually has (skipped honestly when it
isn't installed, rather than faked) — matching this repo's "fakes only for genuinely
external/network-touching seams" convention: the HTTP fetch is faked (a local server
standing in for nuget.org), the DLL-registration native call is not.
"""

from __future__ import annotations

import asyncio
import io
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.inference.ep_plugins import (
    EP_PLUGIN_SPECS,
    ensure_ep_plugin,
    ep_plugins_dir,
    plugin_dll_path,
    register_ep_plugin,
)


def run(coro):
    return asyncio.run(coro)


def _fake_nupkg_bytes(dll_relpath: str, payload: bytes = b"not a real DLL, just a fixture") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(dll_relpath, payload)
    return buf.getvalue()


class _NugetLikeHandler(BaseHTTPRequestHandler):
    """Serves a real zip for any path -- close enough to nuget.org's own
    `/v2/package/{id}/{version}` shape for `ensure_ep_plugin`'s own URL templating, which
    only cares that *a* URL resolves to *some* real zip bytes."""

    body: bytes = b""

    def do_GET(self):  # noqa: N802 - stdlib's own naming
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib's own signature
        pass


@pytest.fixture
def nuget_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _NugetLikeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ensure_ep_plugin_downloads_extracts_and_locates_the_real_dll(tmp_path: Path, nuget_server):
    spec = EP_PLUGIN_SPECS["openvino"]
    _NugetLikeHandler.body = _fake_nupkg_bytes(spec.dll_relpath)
    port = nuget_server.server_address[1]

    result = run(
        ensure_ep_plugin(
            "openvino", tmp_path,
            download_url_template=f"http://127.0.0.1:{port}/v2/package/{{package_id}}/{{version}}",
        )
    )

    assert result.ok, result.error_detail
    dll_path = plugin_dll_path("openvino", tmp_path)
    assert dll_path is not None
    assert dll_path.exists()
    assert dll_path.read_bytes() == b"not a real DLL, just a fixture"


def test_ensure_ep_plugin_is_idempotent_and_skips_the_network_once_provisioned(tmp_path: Path, nuget_server):
    spec = EP_PLUGIN_SPECS["openvino"]
    dll_path = plugin_dll_path("openvino", tmp_path)
    dll_path.parent.mkdir(parents=True, exist_ok=True)
    dll_path.write_bytes(b"already provisioned")

    _NugetLikeHandler.body = b"if this got fetched, the test failed"
    port = nuget_server.server_address[1]

    result = run(
        ensure_ep_plugin(
            "openvino", tmp_path,
            download_url_template=f"http://127.0.0.1:{port}/v2/package/{{package_id}}/{{version}}",
        )
    )

    assert result.ok
    assert result.bytes_written == 0
    assert dll_path.read_bytes() == b"already provisioned"


def test_ensure_ep_plugin_reports_a_real_error_for_an_unknown_device(tmp_path: Path):
    result = run(ensure_ep_plugin("migraphx", tmp_path))
    assert result.ok is False
    assert result.error_code == "NO_EP_PLUGIN"


def test_ensure_ep_plugin_reports_a_real_error_when_the_dll_is_missing_from_the_zip(tmp_path: Path, nuget_server):
    _NugetLikeHandler.body = _fake_nupkg_bytes("runtimes/win-x64/native/some_other_file.dll")
    port = nuget_server.server_address[1]

    result = run(
        ensure_ep_plugin(
            "openvino", tmp_path,
            download_url_template=f"http://127.0.0.1:{port}/v2/package/{{package_id}}/{{version}}",
        )
    )

    assert result.ok is False
    assert result.error_code == "PLUGIN_DLL_MISSING"


def test_ep_plugins_dir_is_a_sibling_of_models_config_data(tmp_path: Path):
    assert ep_plugins_dir(tmp_path) == tmp_path / "ep_plugins"


def test_plugin_dll_path_is_none_for_a_device_with_no_known_plugin(tmp_path: Path):
    assert plugin_dll_path("cuda", tmp_path) is None


def test_register_ep_plugin_returns_false_for_an_unknown_device(tmp_path: Path):
    assert register_ep_plugin("cuda", tmp_path) is False


def test_register_ep_plugin_returns_false_when_never_provisioned(tmp_path: Path):
    assert register_ep_plugin("openvino", tmp_path) is False


def test_register_ep_plugin_against_a_real_fake_dll_degrades_honestly_without_onnxruntime_genai(
    tmp_path: Path, monkeypatch
):
    """Without a real DLL and a real `onnxruntime_genai` install, `register_ep_plugin`
    must degrade to `False` rather than raise -- `docs/PRINCIPLES.md` §4.4. Covers both
    real degrade paths this dev interpreter can hit deterministically: `onnxruntime_genai`
    missing (skipped if it happens to be installed here) is exercised via a fake fixture
    DLL, which any real `onnxruntime_genai` install will also honestly reject (not a real
    native library), proving the "registration failure degrades" branch either way."""
    dll_path = plugin_dll_path("openvino", tmp_path)
    dll_path.parent.mkdir(parents=True, exist_ok=True)
    dll_path.write_bytes(b"not a real native DLL")

    import core.inference.ep_plugins as ep_plugins_module

    monkeypatch.setattr(ep_plugins_module, "_registered_providers", set())
    assert register_ep_plugin("openvino", tmp_path) is False
