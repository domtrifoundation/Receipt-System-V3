"""Which export providers are registered (`v3-deepdive-31-export-framework.md` §2).

A genuinely mutable registry populated at startup, so a plain `dict` and not a `FrozenDict`
— `docs/PRINCIPLES.md` §2.1.1 draws that line explicitly, and the intent should be visible
in the type. The module-level *default roster* below is a constant, so it is a `FrozenDict`.

Adding a format means writing a provider and registering it. It never means touching this
module's dispatch logic, because there is none to touch: `generate()` looks the provider up
and calls it.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from . import errors
from .contracts import ExportProvider, ExportResult


class ExportRegistry:
    """The live registry of export providers."""

    def __init__(self, providers: list[ExportProvider] | None = None) -> None:
        self._providers: dict[str, ExportProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: ExportProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> ExportProvider | None:
        return self._providers.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def generate(
        self, name: str, user_id: str, params: FrozenDict | None = None
    ) -> ExportResult:
        """Run one provider. An unknown or failing provider is a code, never a raise."""
        provider = self._providers.get(name)
        if provider is None:
            return ExportResult(
                ok=False,
                error_code=errors.UNKNOWN_PROVIDER,
                error_detail=f"no export provider named '{name}'; registered: {self.names()}",
            )
        try:
            return await provider.generate(user_id, params or FrozenDict({}))
        except errors.ExportError as exc:
            return ExportResult(ok=False, error_code=exc.code, error_detail=str(exc))
        except Exception as exc:  # noqa: BLE001 - one bad provider never breaks the caller
            return ExportResult(
                ok=False, error_code=errors.GENERATION_FAILED, error_detail=str(exc)
            )


#: The roster a default install registers. A module-level constant lookup table, therefore a
#: `FrozenDict` (§2.1.1) — maps provider name to the module path that defines it, so the
#: roster is readable without importing every provider (and every optional dependency) just
#: to ask what exists.
DEFAULT_PROVIDER_MODULES = FrozenDict(
    {
        "excel_general": "core.persistence.exports.providers.excel_general",
        "slsp_summary": "core.persistence.exports.providers.slsp_summary",
        "audit_package": "core.persistence.exports.providers.audit_package",
        "data_portability": "core.persistence.exports.providers.data_portability",
        "group_export": "core.persistence.exports.providers.group_export",
        "quickbooks": "core.persistence.exports.providers.quickbooks_export",
        "xero": "core.persistence.exports.providers.xero_export",
    }
)


__all__ = ["DEFAULT_PROVIDER_MODULES", "ExportRegistry"]
