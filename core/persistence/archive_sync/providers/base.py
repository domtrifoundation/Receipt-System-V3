"""`SyncTargetProvider` — the Provider Registry for outbound mirror targets (§2).

**This abstraction is a correction, not decoration.** An earlier version of this layout had
the sync logic in a single `sync.py` with no provider seam at all, despite `SyncTarget`
existing as a contract type that plainly implies more than one kind of target — a real
`docs/PRINCIPLES.md` §1.3 violation. Google Drive being the only implemented provider today
is fine; what was not fine was the *structure* making a second one a refactor rather than a
drop-in.

`is_reachable()` is part of the Protocol rather than something inferred from a failed upload,
because §8's notify-then-pause behaviour depends on reachability being a genuinely checkable
state. "The last upload failed" and "the target no longer exists" call for different
responses, and only one of them should pause the whole mirror.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts import SyncResult


@runtime_checkable
class SyncTargetProvider(Protocol):
    """One external destination a user's archive can be mirrored to."""

    name: str

    async def mirror(self, blob_ref: str, target_path: str) -> SyncResult:
        """Upload one blob's bytes to the external target under a generated name."""
        ...

    async def is_reachable(self) -> bool:
        """Whether the configured target folder is present and writable right now."""
        ...


class SyncProviderRegistry:
    """A genuinely mutable registry populated at startup, so a plain `dict` (§2.1.1)."""

    def __init__(self, providers: list[SyncTargetProvider] | None = None) -> None:
        self._providers: dict[str, SyncTargetProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: SyncTargetProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> SyncTargetProvider | None:
        return self._providers.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


class LocalFolderProvider:
    """A real provider that mirrors into a local directory.

    Not a mock: a self-hosted install mirroring to a mounted network share or an attached
    drive is a genuine deployment, and it is also what makes the cursor-resume and
    filename-collision behaviours testable without a network.
    """

    name = "local_folder"

    def __init__(self, root, fetch_bytes) -> None:
        from pathlib import Path  # noqa: PLC0415

        self._root = Path(root)
        self._fetch = fetch_bytes
        self.reachable = True

    async def is_reachable(self) -> bool:
        return self.reachable and self._root.exists()

    async def mirror(self, blob_ref: str, target_path: str) -> SyncResult:
        from ..errors import TARGET_MISSING, UPLOAD_FAILED  # noqa: PLC0415

        if not await self.is_reachable():
            return SyncResult(
                ok=False, error_code=TARGET_MISSING, error_detail=str(self._root)
            )
        data = await self._fetch(blob_ref)
        if data is None:
            return SyncResult(
                ok=False, error_code=UPLOAD_FAILED, error_detail=f"no bytes for {blob_ref}"
            )
        destination = self._root / target_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return SyncResult(ok=True, external_name=target_path)


__all__ = ["LocalFolderProvider", "SyncProviderRegistry", "SyncTargetProvider"]
