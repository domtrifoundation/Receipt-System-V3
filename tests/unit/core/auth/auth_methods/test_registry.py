"""The Provider Registry, and the degradation property §11 asks for by name:

    "confirms `AuthMethodProvider.is_available()` returning `False` for one method (e.g. the
    SMS provider being down) correctly hides only that option from the login screen rather
    than breaking login entirely".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.auth.auth_methods.base import AuthMethodProvider, AuthMethodRegistry
from core.auth.contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    AuthResult,
    ChallengePurpose,
)
from core.auth.tenancy import resolve_profile

from ..conftest import run


@dataclass
class StubProvider:
    stub_method: AuthMethod
    up: bool = True
    explode: bool = False
    initiated: list[str] = field(default_factory=list)

    @property
    def method(self) -> AuthMethod:
        return self.stub_method

    async def is_available(self) -> bool:
        if self.explode:
            raise RuntimeError("the provider's own dependency blew up")
        return self.up

    async def initiate(self, identifier, purpose=ChallengePurpose.LOGIN) -> AuthChallenge:
        self.initiated.append(identifier)
        return AuthChallenge(challenge_id="c", method=self.stub_method, purpose=purpose)

    async def verify(self, challenge_id, response) -> AuthResult:
        return AuthResult(authenticated=True, method=self.stub_method, user_id="u")


@pytest.fixture
def registry():
    return AuthMethodRegistry(StubProvider(m) for m in AuthMethod)


def test_a_stub_satisfies_the_protocol():
    assert isinstance(StubProvider(AuthMethod.EMAIL), AuthMethodProvider)


def test_all_four_methods_are_offered_when_all_are_up(registry, profile):
    assert set(run(registry.offerable(profile))) == set(AuthMethod)


def test_one_down_provider_hides_exactly_one_option(registry, profile):
    registry.get(AuthMethod.SMS).up = False
    offerable = run(registry.offerable(profile))
    assert AuthMethod.SMS not in offerable
    assert {AuthMethod.SSO, AuthMethod.EMAIL, AuthMethod.PASSKEY} <= set(offerable)


def test_a_provider_that_raises_during_its_probe_does_not_break_the_login_screen(
    registry, profile
):
    registry.get(AuthMethod.SMS).explode = True
    statuses = {s.method: s for s in run(registry.availability(profile))}
    assert not statuses[AuthMethod.SMS].available
    assert "probe failed" in statuses[AuthMethod.SMS].detail
    assert statuses[AuthMethod.EMAIL].offerable


def test_an_owner_disabled_method_is_not_offered_even_when_available(registry):
    profile = resolve_profile({"methods_enabled": ["sso", "passkey"]})
    offerable = run(registry.offerable(profile))
    assert set(offerable) == {AuthMethod.SSO, AuthMethod.PASSKEY}


def test_resolve_reports_why_a_method_cannot_be_used(registry, profile):
    registry.get(AuthMethod.SMS).up = False
    provider, error = run(registry.resolve(AuthMethod.SMS, profile))
    assert provider is None and error is AuthError.METHOD_UNAVAILABLE

    disabled = resolve_profile({"methods_enabled": ["sso"]})
    provider, error = run(registry.resolve(AuthMethod.EMAIL, disabled))
    assert provider is None and error is AuthError.METHOD_NOT_ENABLED

    provider, error = run(registry.resolve(AuthMethod.SSO, profile))
    assert error is None and provider is registry.get(AuthMethod.SSO)


def test_an_unregistered_method_is_reported_as_such(profile):
    registry = AuthMethodRegistry([StubProvider(AuthMethod.EMAIL)])
    statuses = {s.method: s for s in run(registry.availability(profile))}
    assert statuses[AuthMethod.SSO].detail == "no provider registered"
    assert statuses[AuthMethod.EMAIL].offerable


def test_registering_a_second_provider_for_a_method_replaces_it(registry):
    replacement = StubProvider(AuthMethod.EMAIL)
    registry.register(replacement)
    assert registry.get(AuthMethod.EMAIL) is replacement
    assert len(registry.registered()) == len(AuthMethod)
