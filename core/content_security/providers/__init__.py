"""Malware-scan providers — the Provider Registry (`docs/PRINCIPLES.md` §1.2, §1.3).

`ClamAVProvider` (local, per-call `clamscan` subprocess, the original default),
`ClamdProvider` (local, talks to an already-running `clamd` daemon instead — no per-call
signature-database reload, see its own module docstring for why that matters under real
concurrency), and `VirusTotalProvider` (cloud, the swappable alternative resolved in §9) all
implement `MalwareScanProvider`; `ProviderRegistry` is what runs however many of them are
enabled at once and returns every result for `pipeline.py`'s own consensus rule to resolve.
"""

from .base import MalwareScanProvider, ProviderRegistry
from .clamav_provider import ClamAVProvider
from .clamd_provider import ClamdProvider
from .virustotal_provider import HttpResponse, HttpTransport, VirusTotalProvider, default_transport

__all__ = [
    "ClamAVProvider",
    "ClamdProvider",
    "HttpResponse",
    "HttpTransport",
    "MalwareScanProvider",
    "ProviderRegistry",
    "VirusTotalProvider",
    "default_transport",
]
