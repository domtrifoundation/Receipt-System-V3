"""Per-user OAuth Drive credentials (deep-dive §4.1.1b) — **implemented, held inactive**.

Gated behind `google_drive.credential_strategy: service_account | oauth`, defaulting to
and currently locked to `service_account`, because per-user OAuth for Drive's scopes
requires passing Google's own OAuth app-verification process (a CASA audit, a multi-week
review) before it can be offered to real users at all. That process being incomplete is
the reason this stays inactive, not a design gap — flipping the default once verification
clears is a config change and a flag-flip, not new code.

**Not live-tested this session**, for the same reason `service_account.py` isn't: no real
Google OAuth client credentials are configured here, and `google-auth-oauthlib` is not
installed in this session's `.venv` either (confirmed: `import google_auth_oauthlib`
raises `ModuleNotFoundError`) — `is_available()` correctly reports `False` in that real
state.

Per the deep-dive's own §4.1's stated concern: **code that's never exercised in production
is exactly the kind of thing that can quietly break** (a library API shift, an expired
test credential) without anyone noticing until the day it's finally switched on — worth a
periodic Telemetrees-tracked check, not a fire-and-forget path (deep-dive §11, owner
assigned to Telemetrees).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...errors import SourceUnavailable

__all__ = ["OAuthConfig", "OAuthCredentialProvider"]

_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str = ""
    client_secret: str = ""
    #: A path to a stored, previously-obtained refresh token — this provider does not run
    #: an interactive consent flow itself (that belongs to a first-run setup screen, not
    #: to a source's own `get_service()` call, which must be non-interactive).
    token_file_path: str = ""


class OAuthCredentialProvider:
    def __init__(self, config: OAuthConfig | None = None) -> None:
        self._config = config or OAuthConfig()
        self._service: Any = None

    def is_available(self) -> bool:
        if not (self._config.client_id and self._config.client_secret and self._config.token_file_path):
            return False
        try:
            import google.auth  # noqa: F401, PLC0415
            import google_auth_oauthlib  # noqa: F401, PLC0415
            import googleapiclient.discovery  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    def get_service(self) -> Any:
        if self._service is not None:
            return self._service
        if not self.is_available():
            raise SourceUnavailable("OAuth Drive credentials are not configured/installed")

        try:
            from google.auth.transport.requests import Request  # noqa: PLC0415
            from google.oauth2.credentials import Credentials  # noqa: PLC0415
            from googleapiclient.discovery import build  # noqa: PLC0415

            credentials = Credentials.from_authorized_user_file(
                self._config.token_file_path, scopes=[_DRIVE_READONLY_SCOPE]
            )
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            self._service = build("drive", "v3", credentials=credentials)
        except Exception as exc:  # noqa: BLE001 - an invalid/expired token is unavailability
            raise SourceUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return self._service
