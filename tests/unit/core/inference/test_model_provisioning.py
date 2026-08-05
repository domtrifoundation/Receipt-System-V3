"""`model_provisioning.py` — real resumable downloads against a real local HTTP server
(matching `test_download_resume.py`'s own discipline), a fake `HubFilesLister` standing in
for the one real network seam this module has (`docs/PRINCIPLES.md` §1.3 — no real Hub
call in a unit test, the same posture `presets.py`'s own tests already established).
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.inference.contracts import ProvisionStatus
from core.inference.model_provisioning import list_remote_variant_files, preset_status, provision_preset


def run(coro):
    return asyncio.run(coro)


#: The real shape `list_remote_variant_files`'s own fake lister returns for `phi4-mini`'s
#: CPU variant -- mirrors the real repo layout `presets.py`'s own tests already pin.
_PHI4_MINI_FILES = (
    ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json", 1520),
    ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx", 100),
    ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/tokenizer.json", 50),
    ("gpu/gpu-int4-rtn-block-32/genai_config.json", 1600),
    ("gpu/gpu-int4-rtn-block-32/model.onnx", 200),
)


def _fake_lister(files=_PHI4_MINI_FILES):
    def lister(repo: str):
        assert repo == "microsoft/Phi-4-mini-instruct-onnx"
        return files
    return lister


# --------------------------------------------------------------------- list_remote_variant_files


def test_list_remote_variant_files_returns_only_the_resolved_variants_own_files():
    files = list_remote_variant_files("phi4-mini", "cpu", hub_lister=_fake_lister())

    by_name = {f.relative_path: f.size_bytes for f in files}
    assert by_name == {"genai_config.json": 1520, "model.onnx": 100, "tokenizer.json": 50}


def test_list_remote_variant_files_unknown_preset_raises_key_error():
    with pytest.raises(KeyError):
        list_remote_variant_files("no-such-preset", "cpu", hub_lister=_fake_lister())


#: The real shape `keisuke-miyako/Qwen2.5-3B-Instruct-onnx-int4` returns -- every file at
#: the repo root, no tagged subfolder, `resolve_variant_path`'s own flat-repo fallback.
_QWEN_FLAT_FILES = (
    ("genai_config.json", 1400),
    ("model.onnx", 120),
    ("model.onnx.data", 3_000_000),
    ("tokenizer.json", 800),
)


def _fake_qwen_lister(files=_QWEN_FLAT_FILES):
    def lister(repo: str):
        assert repo == "keisuke-miyako/Qwen2.5-3B-Instruct-onnx-int4"
        return files
    return lister


def test_list_remote_variant_files_for_a_flat_repo_strips_no_prefix():
    """The real, live-found second repo shape: an empty `resolve_variant_path()` result
    (`variant == ""`, meaning "the repo root itself") must produce an empty prefix, not
    the `"/"` a naive `f"{variant}/"` would -- every filename comes back unchanged, not
    silently excluded because no real path starts with a bare `/`."""
    files = list_remote_variant_files("qwen2.5-3b", "cpu", hub_lister=_fake_qwen_lister())

    by_name = {f.relative_path: f.size_bytes for f in files}
    assert by_name == {
        "genai_config.json": 1400, "model.onnx": 120,
        "model.onnx.data": 3_000_000, "tokenizer.json": 800,
    }


# --------------------------------------------------------------------- preset_status


def test_preset_status_not_downloaded_when_directory_missing(tmp_path: Path):
    status = preset_status("phi4-mini", "cpu", tmp_path, hub_lister=_fake_lister())

    assert status == ProvisionStatus.NOT_DOWNLOADED


def test_preset_status_partial_when_some_files_present(tmp_path: Path):
    preset_dir = tmp_path / "phi4-mini"
    preset_dir.mkdir()
    (preset_dir / "genai_config.json").write_bytes(b"x" * 1520)

    status = preset_status("phi4-mini", "cpu", tmp_path, hub_lister=_fake_lister())

    assert status == ProvisionStatus.PARTIAL


def test_preset_status_partial_when_file_present_but_wrong_size(tmp_path: Path):
    preset_dir = tmp_path / "phi4-mini"
    preset_dir.mkdir()
    (preset_dir / "genai_config.json").write_bytes(b"x" * 1520)
    (preset_dir / "model.onnx").write_bytes(b"x" * 99)  # wrong size -- not the full 100
    (preset_dir / "tokenizer.json").write_bytes(b"x" * 50)

    status = preset_status("phi4-mini", "cpu", tmp_path, hub_lister=_fake_lister())

    assert status == ProvisionStatus.PARTIAL


def test_preset_status_ready_when_every_file_present_at_correct_size(tmp_path: Path):
    preset_dir = tmp_path / "phi4-mini"
    preset_dir.mkdir()
    (preset_dir / "genai_config.json").write_bytes(b"x" * 1520)
    (preset_dir / "model.onnx").write_bytes(b"x" * 100)
    (preset_dir / "tokenizer.json").write_bytes(b"x" * 50)

    status = preset_status("phi4-mini", "cpu", tmp_path, hub_lister=_fake_lister())

    assert status == ProvisionStatus.READY


def test_preset_status_unresolvable_preset_is_not_downloaded(tmp_path: Path):
    status = preset_status("no-such-preset", "cpu", tmp_path, hub_lister=_fake_lister())

    assert status == ProvisionStatus.NOT_DOWNLOADED


# --------------------------------------------------------------------- provision_preset


class _FileServingHandler(BaseHTTPRequestHandler):
    """Serves whatever content `content_by_path` has for the request's own real relative
    path (everything after `/microsoft/Phi-4-mini-instruct-onnx/resolve/main/`) -- the
    real URL shape `provision_preset()` actually constructs."""

    content_by_path: dict[str, bytes] = {}
    requests_seen: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).requests_seen.append(self.path)
        prefix = "/microsoft/Phi-4-mini-instruct-onnx/resolve/main/"
        relative = self.path.removeprefix(prefix)
        body = type(self).content_by_path.get(relative)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        pass


def _start(handler_cls):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd._test_thread = thread  # type: ignore[attr-defined]
    return httpd


def _stop(httpd):
    httpd.shutdown()
    httpd._test_thread.join(timeout=5)  # type: ignore[attr-defined]


def test_provision_preset_downloads_every_missing_file(tmp_path: Path, monkeypatch):
    small_files = (
        ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json", 5),
        ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx", 7),
    )
    _FileServingHandler.content_by_path = {
        "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json": b"AAAAA",
        "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/model.onnx": b"BBBBBBB",
    }
    _FileServingHandler.requests_seen = []
    httpd = _start(_FileServingHandler)
    try:
        port = httpd.server_address[1]

        import core.inference.model_provisioning as mp

        real_download_file = mp.download_file

        async def _redirecting_download_file(url, destination, **kwargs):
            redirected = url.replace("https://huggingface.co", f"http://127.0.0.1:{port}")
            return await real_download_file(redirected, destination, **kwargs)

        monkeypatch.setattr(mp, "download_file", _redirecting_download_file)

        progress_events = []
        report = run(provision_preset(
            "phi4-mini", "cpu", tmp_path,
            on_progress=progress_events.append,
            hub_lister=_fake_lister(small_files),
        ))

        assert report.ok is True
        assert len(report.files) == 2
        assert all(f.ok for f in report.files)

        preset_dir = tmp_path / "phi4-mini"
        assert (preset_dir / "genai_config.json").read_bytes() == b"AAAAA"
        assert (preset_dir / "model.onnx").read_bytes() == b"BBBBBBB"
        assert progress_events  # real progress was reported, not silently skipped
        assert progress_events[-1].files_completed == 2
        assert progress_events[-1].files_total == 2
    finally:
        _stop(httpd)


def test_provision_preset_downloads_a_flat_repo_without_a_double_slash_url(tmp_path: Path, monkeypatch):
    """Real, live-found bug: a flat repo's own `variant == ""` (`resolve_variant_path`'s
    root fallback) made the download URL builder emit `.../resolve/main//model.onnx` --
    a real double slash Hugging Face's server does not normalize, 404s on, and which
    made every single file in a real `qwen2.5-3b` provisioning attempt fail (confirmed
    live: `ok=False`, nothing written to disk, despite `list_remote_variant_files`
    already resolving the identical repo correctly). This test's own handler strips a
    fixed, no-double-slash prefix and 404s on anything else, so a regression here fails
    exactly the way the real provisioning call did."""
    flat_files = (("genai_config.json", 5), ("model.onnx", 7))

    class _FlatFileServingHandler(_FileServingHandler):
        """Same lookup-by-exact-relative-path logic as the base handler, just against
        the real qwen repo's own path prefix. A double-slash URL naturally 404s here
        without any extra detection: `removeprefix` leaves a stray leading `/` that
        never matches a real registered key."""

        content_by_path = {
            "genai_config.json": b"AAAAA",
            "model.onnx": b"BBBBBBB",
        }
        requests_seen: list[str] = []

        def do_GET(self):  # noqa: N802
            type(self).requests_seen.append(self.path)
            prefix = "/keisuke-miyako/Qwen2.5-3B-Instruct-onnx-int4/resolve/main/"
            relative = self.path.removeprefix(prefix)
            body = type(self).content_by_path.get(relative)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002
            pass

    httpd = _start(_FlatFileServingHandler)
    try:
        port = httpd.server_address[1]

        import core.inference.model_provisioning as mp

        real_download_file = mp.download_file

        async def _redirecting_download_file(url, destination, **kwargs):
            redirected = url.replace("https://huggingface.co", f"http://127.0.0.1:{port}")
            return await real_download_file(redirected, destination, **kwargs)

        monkeypatch.setattr(mp, "download_file", _redirecting_download_file)

        report = run(provision_preset(
            "qwen2.5-3b", "cpu", tmp_path, hub_lister=_fake_qwen_lister(flat_files),
        ))

        assert report.ok is True, report
        assert all(f.ok for f in report.files), report.files
        preset_dir = tmp_path / "qwen2.5-3b"
        assert (preset_dir / "genai_config.json").read_bytes() == b"AAAAA"
        assert (preset_dir / "model.onnx").read_bytes() == b"BBBBBBB"
    finally:
        _stop(httpd)


def test_provision_preset_skips_files_already_correct_on_disk(tmp_path: Path, monkeypatch):
    small_files = (("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/genai_config.json", 5),)
    preset_dir = tmp_path / "phi4-mini"
    preset_dir.mkdir()
    (preset_dir / "genai_config.json").write_bytes(b"AAAAA")

    import core.inference.model_provisioning as mp

    async def _never_called(*args, **kwargs):
        raise AssertionError("download_file should not be called for an already-complete file")

    monkeypatch.setattr(mp, "download_file", _never_called)

    report = run(provision_preset("phi4-mini", "cpu", tmp_path, hub_lister=_fake_lister(small_files)))

    assert report.ok is True
    assert report.files[0].ok is True
    assert report.files[0].bytes_written == 0  # nothing downloaded, it was already there


def test_provision_preset_one_file_failing_does_not_stop_the_others(tmp_path: Path, monkeypatch):
    small_files = (
        ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/a.bin", 3),
        ("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/b.bin", 3),
    )

    import core.inference.model_provisioning as mp
    from services.update.proving_grounds.contracts import DownloadResult

    async def _fake_download(url, destination, **kwargs):
        if "a.bin" in url:
            return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_detail="simulated")
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"ccc")
        return DownloadResult(ok=True, destination=str(destination), bytes_written=3)

    monkeypatch.setattr(mp, "download_file", _fake_download)

    report = run(provision_preset("phi4-mini", "cpu", tmp_path, hub_lister=_fake_lister(small_files)))

    assert report.ok is False
    outcomes_by_name = {f.relative_path: f for f in report.files}
    assert outcomes_by_name["a.bin"].ok is False
    assert outcomes_by_name["b.bin"].ok is True  # the other file still succeeded


def test_provision_preset_unknown_preset_reports_error_not_raise(tmp_path: Path):
    report = run(provision_preset("no-such-preset", "cpu", tmp_path, hub_lister=_fake_lister()))

    assert report.ok is False
    assert report.error_code == "PRESET_NOT_CONFIGURED"


def test_provision_preset_unresolvable_device_reports_error_not_raise(tmp_path: Path):
    report = run(provision_preset("phi4-mini", "rocm", tmp_path, hub_lister=_fake_lister()))

    assert report.ok is False
    assert report.error_code == "VARIANT_NOT_FOUND"
