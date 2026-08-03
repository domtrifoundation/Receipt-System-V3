"""Receives the actual webhook POST (deep-dive §5) — provider-specific quirks isolated to
each provider's own handler function, never leaking into the generic subscription/
renewal/Circadian machinery above.

**Drive's own callback quirk**: the POST itself carries no payload, just a signal that
something changed. This handler's entire job on receipt is one follow-up `changes.list()`
call to find out what actually changed, then emit one `ChangeEvent` per changed item.

**Not live-tested this session** — no real Drive credentials/network call made, same
honesty posture as every other unverified Google API call this session (`sources/
google_drive/`, `subscription.py`'s own `DriveWebhookAdapter`).
"""

from __future__ import annotations

from .contracts import ChangeEvent, WebhookProvider

__all__ = ["handle_drive_webhook"]


async def handle_drive_webhook(credentials, start_page_token: str) -> tuple[ChangeEvent, ...]:
    """`start_page_token` is the last known Drive Changes API page token — this handler
    calls `changes.list()` from that token forward and returns one `ChangeEvent` per
    changed item. The caller (this sub-API's own future `service.py`) is responsible for
    persisting the returned `newStartPageToken` for the next call; this function is
    stateless with respect to that token on purpose, matching every other API's own
    "errors and state are the caller's data, not this module's" convention.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    service = await loop.run_in_executor(None, credentials.get_service)
    response = await loop.run_in_executor(
        None,
        lambda: service.changes().list(pageToken=start_page_token, fields="changes(fileId, removed)").execute(),
    )

    events = []
    for change in response.get("changes", []):
        change_type = "removed" if change.get("removed") else "modified"
        events.append(
            ChangeEvent(
                provider=WebhookProvider.GOOGLE_DRIVE,
                file_id=change.get("fileId", ""),
                change_type=change_type,
            )
        )
    return tuple(events)
