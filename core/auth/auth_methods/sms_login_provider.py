"""SMS one-time-code login (deep-dive §4.4).

The same engine as email — `otp.py` — bound to Notifications API's own SMS channel and to a
lookup by phone number. `User.phone_number` is optional and set only where SMS login is
configured, so a user without one simply has no SMS option; the enumeration-safe path in
`otp.py` means an unknown number is not distinguishable from a known one from outside.

**Notifications API owns SMS delivery, including the provider roster** its own deep-dive
names. Auth standing up a second, independent SMS-sending capability would duplicate a
capability that already exists in the system, which is exactly what §4.4 says not to do.
This file's entire job is choosing the channel.

An unconfigured or unreachable SMS provider degrades this method to unavailable — the login
screen drops the SMS option and every other method keeps working (`docs/PRINCIPLES.md`
§4.4). That is the case the deep-dive's own provider-degradation test targets.
"""

from __future__ import annotations

from ..challenges import ChallengeStore
from ..contracts import AuthMethod, InstallProfile
from ..store import UserDirectory
from .notifications import NotificationChannel, UnavailableChannel
from .otp import OtpProvider


class SmsLoginProvider(OtpProvider):
    def __init__(
        self,
        challenges: ChallengeStore,
        directory: UserDirectory,
        profile: InstallProfile,
        channel: NotificationChannel | None = None,
    ) -> None:
        super().__init__(
            method=AuthMethod.SMS,
            channel=channel or UnavailableChannel("sms"),
            challenges=challenges,
            lookup_user=directory.find_by_phone,
            code_length=profile.otp_code_length,
            ttl_seconds=profile.otp_ttl_seconds,
        )


__all__ = ["SmsLoginProvider"]
