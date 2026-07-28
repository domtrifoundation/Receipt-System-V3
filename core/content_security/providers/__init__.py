"""Malware-scan providers — the Provider Registry (`docs/PRINCIPLES.md` §1.2, §1.3).

`ClamAVProvider` (local, subprocess, the default) and `VirusTotalProvider` (cloud, the
swappable alternative resolved in §9) both implement `MalwareScanProvider`; `ProviderRegistry`
is what runs however many of them are enabled at once and returns every result for
`pipeline.py`'s own consensus rule to resolve.
"""

from .base import MalwareScanProvider, ProviderRegistry
from .clamav_provider import ClamAVProvider
from .virustotal_provider import HttpResponse, HttpTransport, VirusTotalProvider, default_transport

__all__ = [
    "ClamAVProvider",
    "HttpResponse",
    "HttpTransport",
    "MalwareScanProvider",
    "ProviderRegistry",
    "VirusTotalProvider",
    "default_transport",
]
