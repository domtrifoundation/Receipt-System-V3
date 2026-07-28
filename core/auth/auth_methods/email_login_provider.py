"""Email one-time-code login (deep-dive §4.4).

Everything real is in `otp.py`, which both code-based methods share. This file is the
binding: the email channel, and looking a user up by the address they typed.

Email is the near-universal identifier on `User` (deep-dive §3), which is why this method
needs no separate enrolment step — any user can receive a code at the address already on
their record. That is also the reason it is the sensible last-resort method to leave enabled
on an install where the operator has not configured SMS.

Delivery goes through Notifications API's own email channel via `notifications.py`; nothing
here composes or sends a message itself.
"""

from __future__ import annotations

from ..challenges import ChallengeStore
from ..contracts import AuthMethod, InstallProfile
from ..store import UserDirectory
from .notifications import NotificationChannel, UnavailableChannel
from .otp import OtpProvider


class EmailLoginProvider(OtpProvider):
    def __init__(
        self,
        challenges: ChallengeStore,
        directory: UserDirectory,
        profile: InstallProfile,
        channel: NotificationChannel | None = None,
    ) -> None:
        super().__init__(
            method=AuthMethod.EMAIL,
            channel=channel or UnavailableChannel("email"),
            challenges=challenges,
            lookup_user=directory.find_by_email,
            code_length=profile.otp_code_length,
            ttl_seconds=profile.otp_ttl_seconds,
        )


__all__ = ["EmailLoginProvider"]
