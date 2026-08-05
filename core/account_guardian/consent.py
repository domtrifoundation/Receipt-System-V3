"""Terms-of-Service / Privacy-Policy consent tracking (deep-dive §7).

**Not in the deep-dive's §2 package layout at all.** §2 was written before §7 — the deep-dive
itself calls this "a real gap surfaced by a corpus-wide sweep" and gives it a full data model
(`ConsentRecord`), two gRPC RPCs, and its own enforcement rule (§7.4), all inside the same
document. That is, by `docs/PRINCIPLES.md` §1.8's own threshold, arguably a real feature that
should have been extracted rather than left as a subsection — but that call belongs to the
planning corpus, not to this implementation pass, so this module is added here rather than
left unbuilt because the original file layout never named it.

**What this module does *not* do**: draft, store, or render the actual legal text. §7.1 is
explicit that the document text is owner-configurable content in the top-level config
directory (`docs/PRINCIPLES.md` §1.6) — `PolicyVersion.text_ref` is a pointer into that
content, never the text itself, and this module has no opinion about what any operator's
policy says.

**Re-consent is an owner judgment call, not an algorithm** (§7.3): `publish_version()` takes
`requires_reconsent` as a plain boolean parameter the owner sets when publishing a revision.
Nothing here tries to diff two versions and decide materiality.

**The enforcement gate** (§7.4): `check_consent()` reports whether the caller's session
should be blocked from everything except viewing/accepting the current policy. It is the
same shape as any other read in this package — a `ConsentCheckResult` with `.error`, never a
raise — because unlike a session/role check, "you have not re-consented yet" is Account
Guardian's own business rule, not Auth's carve-out (`docs/PRINCIPLES.md` §4.1).
`errors.ReconsentRequired` exists for a caller (`service.py`) that wants to gate a whole RPC
on this in one line rather than branching on the result by hand.
"""

from __future__ import annotations

from datetime import datetime

from .contracts import ConsentCheckResult, ConsentDocumentType, ConsentRecord, PolicyVersion, utcnow
from .errors import InvalidRequest, ReconsentRequired
from .store import AccountGuardianDatabase, in_thread


def _row_to_version(row) -> PolicyVersion:
    return PolicyVersion(
        document_type=ConsentDocumentType(row["document_type"]),
        version=row["version"],
        published_at=datetime.fromisoformat(row["published_at"]),
        text_ref=row["text_ref"] or "",
        requires_reconsent=bool(row["requires_reconsent"]),
    )


def _current_version_sync(
    db: AccountGuardianDatabase, document_type: ConsentDocumentType
) -> PolicyVersion | None:
    row = db.query_one(
        "SELECT * FROM policy_versions WHERE document_type = ? AND is_current = 1",
        (document_type.value,),
    )
    return _row_to_version(row) if row else None


async def current_version(
    db: AccountGuardianDatabase, document_type: ConsentDocumentType
) -> PolicyVersion | None:
    return await in_thread(_current_version_sync, db, document_type)


async def publish_version(
    db: AccountGuardianDatabase,
    document_type: ConsentDocumentType,
    version: str,
    text_ref: str,
    *,
    requires_reconsent: bool = False,
    published_at: datetime | None = None,
) -> PolicyVersion:
    """An owner action, not a user-facing RPC (§7.1) — there is no ownership check here
    because the caller (`service.py`) is expected to have already enforced owner-only access
    at the Gateway layer, the same "Auth produces the role claim, each API acts on it"
    division the whole cluster follows (Auth deep-dive §6.1)."""
    if not version or not version.strip():
        raise InvalidRequest("a policy version identifier is required")
    moment = published_at or utcnow()

    def _write() -> None:
        # Unset whatever was current first — the partial unique index on `is_current = 1`
        # would otherwise reject the insert outright, and doing it in the opposite order
        # would leave a real window with no current version at all.
        db.write(
            "UPDATE policy_versions SET is_current = 0 WHERE document_type = ? AND is_current = 1",
            (document_type.value,),
        )
        db.write(
            "INSERT INTO policy_versions (document_type, version, requires_reconsent,"
            " published_at, text_ref, is_current) VALUES (?,?,?,?,?,1)"
            " ON CONFLICT(document_type, version) DO UPDATE SET"
            " requires_reconsent=excluded.requires_reconsent, text_ref=excluded.text_ref,"
            " published_at=excluded.published_at, is_current=1",
            (
                document_type.value, version, int(requires_reconsent), moment.isoformat(),
                text_ref,
            ),
        )

    await in_thread(_write)
    return PolicyVersion(
        document_type=document_type, version=version, published_at=moment, text_ref=text_ref,
        requires_reconsent=requires_reconsent,
    )


async def record_consent(
    db: AccountGuardianDatabase,
    user_id: str,
    document_type: ConsentDocumentType,
    document_version: str,
    ip_address: str | None = None,
) -> ConsentRecord:
    """Tied to a *specific* version (§7.2) — publishing a new one never retroactively counts
    as this call having happened again."""
    now = utcnow()

    def _write() -> None:
        db.write(
            "INSERT INTO consent_records (user_id, document_type, document_version,"
            " accepted_at, ip_address) VALUES (?,?,?,?,?)"
            " ON CONFLICT(user_id, document_type, document_version) DO UPDATE SET"
            " accepted_at=excluded.accepted_at, ip_address=excluded.ip_address",
            (user_id, document_type.value, document_version, now.isoformat(), ip_address),
        )

    await in_thread(_write)
    return ConsentRecord(
        user_id=user_id, document_type=document_type, document_version=document_version,
        accepted_at=now, ip_address=ip_address,
    )


def _has_record_sync(
    db: AccountGuardianDatabase, user_id: str, document_type: ConsentDocumentType, version: str
) -> bool:
    row = db.query_one(
        "SELECT 1 FROM consent_records WHERE user_id = ? AND document_type = ?"
        " AND document_version = ? LIMIT 1",
        (user_id, document_type.value, version),
    )
    return row is not None


async def check_consent(
    db: AccountGuardianDatabase, user_id: str, document_type: ConsentDocumentType
) -> ConsentCheckResult:
    """§7.4's enforcement query. `has_valid_consent` is `True` whenever there is nothing to
    gate on: no version has ever been published, or the current one does not require
    re-consent — the gate only bites for a `requires_reconsent=True` version the caller has
    no matching `ConsentRecord` for, exactly the deep-dive's own wording."""
    version = await current_version(db, document_type)
    if version is None:
        return ConsentCheckResult(has_valid_consent=True, current_version=None)
    if not version.requires_reconsent:
        return ConsentCheckResult(has_valid_consent=True, current_version=version)
    satisfied = await in_thread(_has_record_sync, db, user_id, document_type, version.version)
    return ConsentCheckResult(has_valid_consent=satisfied, current_version=version)


async def assert_consented(
    db: AccountGuardianDatabase, user_id: str, document_type: ConsentDocumentType
) -> None:
    """Raising form for a caller that wants one line to gate a whole RPC on (`service.py`).
    Internal only — never crosses the gRPC boundary; `service.py` catches this and turns it
    into a data result on every RPC except the two consent RPCs themselves, which must stay
    reachable or a blocked caller could never clear the gate."""
    result = await check_consent(db, user_id, document_type)
    if not result.has_valid_consent:
        raise ReconsentRequired(
            f"user {user_id!r} has not accepted {document_type.value} version "
            f"{result.current_version.version if result.current_version else '?'!r}"
        )


__all__ = [
    "assert_consented", "check_consent", "current_version", "publish_version", "record_consent",
]
