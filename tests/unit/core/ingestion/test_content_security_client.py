"""`ContentSecurityClient` (deep-dive §6) — real gRPC calls against a real, in-process
Content Security service, not mocked. Confirms the fail-closed guarantee both ways: a
real service with no scan provider configured denies (`docs/PRINCIPLES.md` §4.2's own
correct behavior), and an unreachable service raises `ContentSecurityUnavailable` rather
than assuming safe.
"""

from __future__ import annotations

import asyncio

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.content_security.providers.base import ProviderRegistry  # noqa: E402
from core.content_security.service import serve as cs_serve  # noqa: E402
from core.ingestion.content_security_client import ContentSecurityClient  # noqa: E402
from core.ingestion.errors import ContentSecurityUnavailable  # noqa: E402

from .conftest import AlwaysCleanProvider  # noqa: E402


@pytest.mark.slow
def test_scan_fails_closed_with_no_provider_configured():
    server = cs_serve("127.0.0.1:19740")
    try:
        client = ContentSecurityClient("127.0.0.1:19740")
        result = asyncio.run(client.scan(b"hello world", claimed_mime_type="image/jpeg"))
        assert result.safe is False
        assert result.error_code == "NO_SCAN_PROVIDER_AVAILABLE"
    finally:
        server.stop(None)


@pytest.mark.slow
def test_scan_reports_safe_through_a_real_clean_provider():
    registry = ProviderRegistry()
    registry.register(AlwaysCleanProvider())
    server = cs_serve("127.0.0.1:19741", registry=registry)
    try:
        client = ContentSecurityClient("127.0.0.1:19741")
        result = asyncio.run(client.scan(b"hello world", claimed_mime_type="image/jpeg"))
        assert result.safe is True
    finally:
        server.stop(None)


@pytest.mark.slow
def test_unreachable_service_raises_content_security_unavailable():
    client = ContentSecurityClient("127.0.0.1:19749", timeout_seconds=1.0)  # nothing listening
    with pytest.raises(ContentSecurityUnavailable):
        asyncio.run(client.scan(b"data"))
