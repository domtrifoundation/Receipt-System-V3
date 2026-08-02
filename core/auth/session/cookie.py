"""Session cookie issuance/validation and the CSRF synchronizer token (deep-dive §5.4).

The cookie is `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`. `SameSite=Lax` is the right
value given Gateway's same-origin design — webapp and API share one origin, so there is no
legitimate cross-site case to accommodate and none of `SameSite=None; Secure`'s browser
quirks to inherit.

**`SameSite=Lax` alone is not treated as sufficient**, and that is the whole point of this
module having a second half. Lax still permits a top-level navigation to carry the cookie,
and this system's mutating actions include break-glass grants and role changes — requests
where a forgery has real consequences. So a per-session synchronizer token is issued
alongside the cookie and checked on every state-changing request.

The check **fails closed** (`docs/PRINCIPLES.md` §4.2): a missing token, an unknown session,
or a token that cannot be compared is a rejection, never a pass-through. There is no
"CSRF check unavailable, allow it" branch here and there must never be one.

Cookie parsing uses the stdlib `http.cookies` behind one small function rather than being
open-coded at call sites — the same external-dependency-behind-an-adapter discipline
(`docs/PRINCIPLES.md` §1.3) applied to a stdlib module, because the parsing quirks are
exactly the sort of thing that should live in one place.
"""

from __future__ import annotations

import hmac
from http.cookies import SimpleCookie

from common.frozen_dict import FrozenDict

from ..contracts import AuthError

#: The cookie name. Not `session` — a specific name avoids colliding with anything else
#: served from the same origin, and the `__Host-` prefix is deliberately *not* used because
#: it forbids `Domain` and mandates `Secure`, which would break a plain-HTTP localhost
#: developer install for no gain on a same-origin deployment that already sets Secure.
SESSION_COOKIE_NAME = "resibo_session"
CSRF_HEADER_NAME = "X-Resibo-CSRF"

#: Methods whose requests must carry a valid synchronizer token. GET/HEAD/OPTIONS are
#: excluded because they are not supposed to change state — an endpoint that mutates on GET
#: is the bug, and moving it to POST is the fix, not widening this set.
MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Attributes applied to every issued cookie. A module-level constant nothing should write,
#: so `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1).
COOKIE_ATTRIBUTES: FrozenDict = FrozenDict({
    "Path": "/",
    "SameSite": "Lax",
    "HttpOnly": True,
    "Secure": True,
})


def build_set_cookie(
    session_id: str, max_age_seconds: int, secure: bool = True
) -> str:
    """The `Set-Cookie` header value for a freshly issued session.

    `secure=False` exists only for a plain-HTTP localhost developer install. It is an
    explicit argument rather than an inferred default precisely so that turning it off is a
    visible decision at the call site instead of something that quietly happens.
    """
    parts = [f"{SESSION_COOKIE_NAME}={session_id}", f"Max-Age={max_age_seconds}"]
    for key, value in COOKIE_ATTRIBUTES.items():
        if key == "Secure":
            if secure:
                parts.append("Secure")
            continue
        parts.append(key if value is True else f"{key}={value}")
    return "; ".join(parts)


def build_clear_cookie(secure: bool = True) -> str:
    """Sent on revocation. The server-side row is what actually ends the session — this
    just stops the browser re-presenting a session id that is already dead."""
    parts = [f"{SESSION_COOKIE_NAME}=", "Max-Age=0"]
    for key, value in COOKIE_ATTRIBUTES.items():
        if key == "Secure":
            if secure:
                parts.append("Secure")
            continue
        parts.append(key if value is True else f"{key}={value}")
    return "; ".join(parts)


def read_session_cookie(cookie_header: str | None) -> str | None:
    """Extract the session id from a `Cookie:` header, or `None` if it is not there."""
    if not cookie_header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        # A malformed header is an absent session, never a partially-trusted one.
        return None
    morsel = jar.get(SESSION_COOKIE_NAME)
    return morsel.value if morsel and morsel.value else None


def requires_csrf(method: str) -> bool:
    return method.upper() in MUTATING_METHODS


def check_csrf(
    method: str, presented: str | None, expected: str | None
) -> AuthError | None:
    """Returns `None` when the request may proceed, or the error that rejects it.

    Returned rather than raised on purpose, and the distinction is worth being precise
    about: this is not a session or role failure, it is a *request-shape* failure that
    Gateway turns into a 403 at the edge — the request never reaches a domain API either
    way, so there is no caller downstream who could ignore it into an access grant.

    Fails closed on every uncertainty: no expected token (unknown or dead session), no
    presented token, or a mismatch — all rejections.
    """
    if not requires_csrf(method):
        return None
    if not expected or not presented:
        return AuthError.CSRF_TOKEN_INVALID
    if not hmac.compare_digest(presented, expected):
        return AuthError.CSRF_TOKEN_INVALID
    return None


__all__ = [
    "COOKIE_ATTRIBUTES", "CSRF_HEADER_NAME", "MUTATING_METHODS", "SESSION_COOKIE_NAME",
    "build_clear_cookie", "build_set_cookie", "check_csrf", "read_session_cookie",
    "requires_csrf",
]
