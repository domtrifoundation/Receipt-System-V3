"""Service-account Drive credentials (deep-dive §4.1.1a) — the only Drive credential
strategy actually usable today. A user shares their receipts folder with a designated
service-account email, the same action as sharing with a colleague — no OAuth consent
screen involved.

**Not live-tested this session** — no real Google Cloud service-account key is configured
in this environment, and using one would mean a real network call to Google's own APIs,
which this session does not make without a real reason to (there was nothing to
download/authenticate for). Built directly from `google-api-python-client`'s/`google-auth`'s
own published API (`service_account.Credentials.from_service_account_file` +
`googleapiclient.discovery.build`), the same honesty posture `core/inference/backends/
onnx_genai_backend.py`'s own module docstring takes for its own unverified library calls.
`google-api-python-client`/`google-auth` are not installed in this session's own `.venv`
either (confirmed: `import googleapiclient`/`import google.auth` both raise
`ModuleNotFoundError` here) — `get_service()` below correctly reports unavailable in that
real, live-confirmed state, which is itself the graceful-degradation path this module
exists to prove works (`docs/PRINCIPLES.md` §4.4), not a gap in what got tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...errors import SourceUnavailable

__all__ = ["ServiceAccountCredentialProvider", "ServiceAccountConfig"]

_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


@dataclass(frozen=True)
class ServiceAccountConfig:
    key_file_path: str = ""  # empty = not configured, regardless of sources_enabled


class ServiceAccountCredentialProvider:
    def __init__(self, config: ServiceAccountConfig | None = None) -> None:
        self._config = config or ServiceAccountConfig()
        self._service: Any = None

    def is_available(self) -> bool:
        if not self._config.key_file_path:
            return False
        try:
            import google.auth  # noqa: F401, PLC0415
            import googleapiclient.discovery  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    def get_service(self) -> Any:
        if self._service is not None:
            return self._service
        if not self._config.key_file_path:
            raise SourceUnavailable("no service-account key file configured")
        try:
            from google.oauth2 import service_account  # noqa: PLC0415
            from googleapiclient.discovery import build  # noqa: PLC0415
        except ImportError as exc:
            raise SourceUnavailable(f"google-api-python-client/google-auth not installed: {exc}") from exc

        try:
            credentials = service_account.Credentials.from_service_account_file(
                self._config.key_file_path, scopes=[_DRIVE_READONLY_SCOPE]
            )
            self._service = build("drive", "v3", credentials=credentials)
        except Exception as exc:  # noqa: BLE001 - a bad/missing key file is unavailability
            raise SourceUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return self._service
