"""Wiring: config in, a ready `AuthServicer` out.

Every other module in this package takes its collaborators as constructor arguments and
constructs none of them. That is what makes them testable without a database or a network,
and it leaves exactly one file that has to know how the pieces fit — this one. Adding a
fifth authentication method means registering it here and nowhere else.

The registry is populated with all four providers even when their dependencies are missing.
That is deliberate rather than an oversight: a provider that reports itself unavailable
produces an honest, specific "SMS is unavailable" on the login screen, whereas an unregistered
provider produces "no provider registered", which reads like a configuration mistake rather
than a service being down. Either way the login screen keeps working with the remaining
methods (`docs/PRINCIPLES.md` §4.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .auth_methods.base import AuthMethodRegistry
from .auth_methods.email_login_provider import EmailLoginProvider
from .auth_methods.notifications import NotificationChannel, UnavailableChannel
from .auth_methods.passkey_provider import PasskeyProvider
from .auth_methods.sms_login_provider import SmsLoginProvider
from .auth_methods.sso_provider import OidcProviderConfig, SsoProvider
from .auth_methods.two_factor import TwoFactorGate
from .break_glass.grant import AuditSink, BreakGlassLedger
from .challenges import ChallengeStore
from .contracts import InstallProfile
from .metrics import AuthMetrics
from .service import AuthServicer
from .session.session_store import SessionStore
from .store import AuthDatabase, UserDirectory
from .tenancy import resolve_profile


def oidc_config(config: Mapping | None) -> OidcProviderConfig:
    """Read the `oidc` subtree of §10's config surface.

    Only the first entry of `providers_enabled` is built today, because Google is the only
    provider configured. The registry shape (§4.1) is what makes a second one an entry here
    rather than a change anywhere else — the structural readiness exists independently of
    when the business decision to add one is made.
    """
    cfg: Mapping = config if isinstance(config, Mapping) else {}
    oidc = cfg.get("oidc")
    oidc = oidc if isinstance(oidc, Mapping) else {}
    enabled = tuple(oidc.get("providers_enabled") or ("google",))
    name = str(enabled[0]) if enabled else "google"
    provider = oidc.get(name)
    provider = provider if isinstance(provider, Mapping) else {}
    return OidcProviderConfig(
        name=name,
        client_id=str(provider.get("client_id", "")),
        client_secret=str(provider.get("client_secret", "")),
        redirect_uri=str(provider.get("redirect_uri", "")),
    )


def build_servicer(
    config: Mapping | None = None,
    db_path: Path | str | None = None,
    email_channel: NotificationChannel | None = None,
    sms_channel: NotificationChannel | None = None,
    audit_sink: AuditSink | None = None,
    db: AuthDatabase | None = None,
) -> AuthServicer:
    """Assemble the whole API from the `auth:` config subtree.

    `email_channel`/`sms_channel` are injected because Notifications API owns delivery
    (§4.4) and Auth must not reach for a transport itself. They default to unavailable,
    which is the honest state until Notifications is implemented.
    """
    profile: InstallProfile = resolve_profile(config)
    database = db or AuthDatabase(db_path)
    directory = UserDirectory(database)
    challenges = ChallengeStore(database)
    metrics = AuthMetrics()

    registry = AuthMethodRegistry([
        SsoProvider(challenges, directory, oidc_config(config)),
        PasskeyProvider(challenges, directory, rp_id=profile.passkey_rp_id),
        EmailLoginProvider(
            challenges, directory, profile, email_channel or UnavailableChannel("email")
        ),
        SmsLoginProvider(
            challenges, directory, profile, sms_channel or UnavailableChannel("sms")
        ),
    ])

    return AuthServicer(
        profile=profile,
        registry=registry,
        sessions=SessionStore(database, profile.session_ttl_hours),
        directory=directory,
        two_factor=TwoFactorGate(directory, profile),
        break_glass=BreakGlassLedger(
            database, profile.break_glass_default_minutes,
            profile.break_glass_max_minutes, audit_sink,
        ),
        challenges=challenges,
        metrics=metrics,
    )


__all__ = ["build_servicer", "oidc_config"]
