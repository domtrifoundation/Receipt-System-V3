"""`AuthMethodProvider` — the Provider Registry behind every way of proving identity.

Four concrete providers sit behind one interface (deep-dive §4.1): SSO/OIDC, passkeys, email
OTP, SMS OTP. This is the same swappable-never-hardcoded discipline (`docs/PRINCIPLES.md`
§1.2–§1.3) every other pluggable capability in this project uses, applied here rather than
excepted because the subject happens to be authentication.

**How this registry's multiplicity works, since §1.2 has two shapes.** Several providers are
registered and *offered simultaneously* — the login screen lists every method that is both
enabled by the owner and currently available. Exactly one is *used* per login, because
authentication is inherently single-choice at the moment of use (§1.2's own stated
exception, the same shape as an SSO provider chosen per-login). Running two methods in
parallel for one login would produce no corroboration value, unlike OCR engines; running two
*second factors* would only produce annoyance. So: many offered, one selected.

**Degradation is per-provider and total.** `availability()` isolates every provider behind
its own try/except: an SMS gateway that is down, or whose optional dependency was never
installed, hides the SMS option and nothing else (`docs/PRINCIPLES.md` §4.4). A login screen
that breaks because one method is unreachable is the failure this is written to prevent.

There is no password provider, and this Protocol is the reason there structurally cannot
casually be one: every method here proves identity by delegated trust, cryptographic
possession, or proof of channel access. A memorized secret is none of those three.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from ..contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    AuthResult,
    ChallengePurpose,
    InstallProfile,
    MethodAvailability,
)
from ..store import in_thread

__all__ = [
    "AuthMethodProvider", "AuthMethodRegistry", "off_event_loop",
]


async def off_event_loop(fn, *args, **kwargs):
    """Run deliberately expensive work in a worker thread.

    Re-exported from `store.in_thread` under the name that says *why* a provider is calling
    it. This API's own rule is concrete: any deliberately CPU-expensive cryptographic work
    must not execute on the event loop, because doing so blocks every other concurrent
    request behind it. Passkey signature verification goes through here for that reason.
    (There is, deliberately, no password hashing to run here — the most expensive
    cryptographic operation in most auth systems does not exist in this one at all.)
    """
    return await in_thread(fn, *args, **kwargs)


@runtime_checkable
class AuthMethodProvider(Protocol):
    """The deep-dive's §4.1 Protocol, with `purpose` threaded through.

    `purpose` is the one addition to the sketched signature and it is load-bearing: §4.5's
    step-up re-authentication re-runs these same providers as a gate rather than as a fresh
    login, and a step-up challenge must not be redeemable as a login (or vice versa). Making
    it a parameter here means every provider gets that separation from the shared challenge
    store instead of each one inventing its own.
    """

    @property
    def method(self) -> AuthMethod: ...

    async def initiate(
        self, identifier: str, purpose: ChallengePurpose = ChallengePurpose.LOGIN
    ) -> AuthChallenge: ...

    async def verify(self, challenge_id: str, response: str) -> AuthResult: ...

    async def is_available(self) -> bool: ...


class AuthMethodRegistry:
    """Holds the registered providers.

    A plain mutable `dict`, not a `FrozenDict`: this is a genuinely mutable internal
    registry populated at startup, which `docs/PRINCIPLES.md` §2.1.1 explicitly excludes
    from the constant rule. The distinction is intent, and the type is where it shows.
    """

    def __init__(self, providers: Iterable[AuthMethodProvider] = ()) -> None:
        self._providers: dict[AuthMethod, AuthMethodProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: AuthMethodProvider) -> None:
        self._providers[provider.method] = provider

    def get(self, method: AuthMethod) -> AuthMethodProvider | None:
        return self._providers.get(method)

    def registered(self) -> tuple[AuthMethod, ...]:
        return tuple(self._providers)

    async def _one_availability(
        self, method: AuthMethod, profile: InstallProfile
    ) -> MethodAvailability:
        enabled = method in profile.methods_enabled
        provider = self._providers.get(method)
        if provider is None:
            return MethodAvailability(
                method=method, enabled=enabled, available=False,
                detail="no provider registered",
            )
        try:
            available = await provider.is_available()
        except Exception as exc:  # noqa: BLE001 - deliberate: see module docstring
            # One provider's failure is one hidden option. Catching broadly here is the
            # point: a provider's own dependency raising something unexpected must not
            # propagate into "the login screen is down".
            return MethodAvailability(
                method=method, enabled=enabled, available=False,
                detail=f"probe failed: {type(exc).__name__}: {exc}",
            )
        return MethodAvailability(
            method=method, enabled=enabled, available=available,
            detail="" if available else "provider reports unavailable",
        )

    async def availability(self, profile: InstallProfile) -> tuple[MethodAvailability, ...]:
        """What the login screen should offer, probed concurrently.

        Concurrent because these are network probes and this API is I/O-bound end to end
        (deep-dive §8.1) — probing four methods serially would make the login screen's
        first paint the sum of four round trips.
        """
        methods = tuple(AuthMethod)
        results = await asyncio.gather(
            *(self._one_availability(m, profile) for m in methods)
        )
        return tuple(results)

    async def offerable(self, profile: InstallProfile) -> tuple[AuthMethod, ...]:
        return tuple(a.method for a in await self.availability(profile) if a.offerable)

    async def resolve(
        self, method: AuthMethod, profile: InstallProfile
    ) -> tuple[AuthMethodProvider | None, AuthError | None]:
        """The single gate every login goes through: enabled, registered, available.

        Returns the error as data — a method that cannot be used yields no session, so a
        caller ignoring this is not thereby authenticated (`errors.py`'s split).
        """
        if method not in profile.methods_enabled:
            return None, AuthError.METHOD_NOT_ENABLED
        provider = self._providers.get(method)
        if provider is None:
            return None, AuthError.METHOD_UNAVAILABLE
        try:
            if not await provider.is_available():
                return None, AuthError.METHOD_UNAVAILABLE
        except Exception:  # noqa: BLE001 - unavailable, not fatal; see module docstring
            return None, AuthError.METHOD_UNAVAILABLE
        return provider, None
