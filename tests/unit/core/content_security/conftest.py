"""Shared fixtures for Content Security's unit tests.

**Every provider here is a real implementation of the `MalwareScanProvider` protocol, not a
mock.** That matters more in this package than elsewhere: the guarantee under test is that
*no* provider behaviour — clean, malicious, disagreeing, timing out, crashing, unavailable —
can produce anything other than a correct verdict, and a mock that returns whatever the test
told it to tests the mock. These fakes go through the same `ProviderRegistry.scan_all` path
production does, including its timeout and availability handling.

The archive builders make real zip bytes. §3's whole argument is that container metadata is
read before extraction, and a fixture that handed the bomb check a fabricated `BombCheckResult`
would skip the only code that argument is about.
"""

from __future__ import annotations

import asyncio
import io
import zipfile

import pytest

from core.content_security.contracts import ProviderScanResult, ScanOutcome
from core.content_security.providers.base import ProviderRegistry

#: A minimal but genuinely valid PNG header — `magic_bytes.detect` reads the real signature,
#: so a placeholder like `b"fake image"` would be detected as text and the test would pass or
#: fail for reasons unrelated to what it claims to check.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.7\n" + b"%\xe2\xe3\xcf\xd3\n" + b"0" * 64


def run(coro):
    """Drive one coroutine to completion.

    `asyncio.run` rather than `pytest-asyncio` because this repo deliberately does not carry
    that dependency — adding one to the test tree for what this already does would put a
    package in `requirements.txt` and in `noxfile.py`'s narrow `FORWARD_COMPAT_DEPS` list for
    no behavioural gain. `core/audit`'s own conftest makes the same call for the same reason.
    """
    return asyncio.run(coro)


class FakeProvider:
    """A real provider that answers however the test needs, through the production path."""

    def __init__(
        self,
        name: str,
        outcome: ScanOutcome = ScanOutcome.CLEAN,
        *,
        available: bool = True,
        raises: BaseException | None = None,
        hangs: bool = False,
        signature_name: str | None = None,
    ) -> None:
        self._name = name
        self._outcome = outcome
        self._available = available
        self._raises = raises
        self._hangs = hangs
        self._signature = signature_name
        self.scan_calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return self._available

    async def scan(self, content: bytes, *, blob_ref: str = "") -> ProviderScanResult:
        self.scan_calls += 1
        if self._hangs:
            await asyncio.sleep(3600)
        if self._raises is not None:
            raise self._raises
        return ProviderScanResult(
            provider_name=self._name,
            outcome=self._outcome,
            signature_name=self._signature,
        )


def registry_of(*providers) -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return registry


def make_zip(members: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """Real zip bytes, because the bomb check reads real `infolist()` metadata."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


@pytest.fixture
def clean_provider() -> FakeProvider:
    return FakeProvider("clamav", ScanOutcome.CLEAN)


@pytest.fixture
def png() -> bytes:
    return PNG_BYTES


@pytest.fixture
def pdf() -> bytes:
    return PDF_BYTES
