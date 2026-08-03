"""Assembles a real `GoogleDriveSource` from config (deep-dive §4.1, §9's own config
sketch: `google_drive.credential_strategy: service_account | oauth`).

**This assembly point was the actual missing piece, not any individual module** — every
Google Drive module (`credential_provider.py`, `service_account.py`, `oauth.py`,
`drive_source.py`) existed and was tested in isolation, but nothing ever read
`credential_strategy` and picked one, and nothing ever constructed a `GoogleDriveSource`
and registered it into `SourceRegistry` at all. `service.py`'s own `SourceRegistry`
previously only ever had `SourceKind.DIRECT_UPLOAD` in it — Drive was completely
unreachable through the running service regardless of how it was configured, a real gap
caught only by checking that every built module actually gets used, not just that it
exists and has its own tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import BlobStoreGateway
from .sources.google_drive.credential_provider import DriveCredentialProvider
from .sources.google_drive.drive_source import DriveSourceConfig, GoogleDriveSource
from .sources.google_drive.oauth import OAuthConfig, OAuthCredentialProvider
from .sources.google_drive.service_account import ServiceAccountConfig, ServiceAccountCredentialProvider

__all__ = ["GoogleDriveConfig", "build_google_drive_source"]


@dataclass(frozen=True)
class GoogleDriveConfig:
    #: `"service_account" | "oauth"` (deep-dive §4.1.1) — `oauth` stays inactive in
    #: practice today since `OAuthCredentialProvider.is_available()` requires real
    #: client credentials + a stored token this project has none of yet, but the
    #: strategy switch itself is real, not hardcoded to one path.
    credential_strategy: str = "service_account"
    service_account: ServiceAccountConfig = field(default_factory=ServiceAccountConfig)
    oauth: OAuthConfig = field(default_factory=OAuthConfig)
    drive_source: DriveSourceConfig = field(default_factory=DriveSourceConfig)
    #: Gateway's own Cloudflare Tunnel endpoint (deep-dive §4.1.3) that Drive's
    #: `files.watch()` call is told to POST to — empty means webhook push notifications
    #: are not registerable yet (the fallback poll path, §4.1.2, still works regardless).
    webhook_callback_url: str = ""
    #: §9's own config values. Renewal itself runs as a Background Worker (deep-dive
    #: §4.1.3 — a separate API this repo hasn't built yet), so this project has no
    #: scheduler calling `WebhookManager.renew()` proactively yet; the value is stored on
    #: `WebhookManager` for that future caller to read, not enforced by a timer this
    #: module invents itself. `fallback_poll_interval_hours`, by contrast, IS enforced
    #: right now — it configures `CircadianMonitor`'s own real delivery-rhythm check.
    webhook_renewal_lead_time_hours: int = 24
    fallback_poll_interval_hours: int = 24


def build_credential_provider(config: GoogleDriveConfig) -> DriveCredentialProvider:
    """Public — `service.py` reuses the exact same credential provider instance for both
    `GoogleDriveSource` (regular downloads) and `DriveWebhookAdapter` (webhook
    registration/renewal), rather than each independently resolving its own credentials
    and potentially disagreeing about which strategy is active."""
    if config.credential_strategy == "oauth":
        return OAuthCredentialProvider(config.oauth)
    # Anything else, including an unrecognized string, degrades to the default rather
    # than raising over a config typo (`docs/PRINCIPLES.md` §4.4) — service-account is
    # "the only strategy usable today" per the deep-dive's own framing anyway.
    return ServiceAccountCredentialProvider(config.service_account)


def build_google_drive_source(
    credentials: DriveCredentialProvider,
    config: GoogleDriveConfig,
    blob_store: BlobStoreGateway,
    metrics=None,
) -> GoogleDriveSource:
    return GoogleDriveSource(credentials, blob_store, config.drive_source, metrics)
