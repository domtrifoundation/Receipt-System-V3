"""Concrete export providers, plus `build_default_registry` to register the standard set."""

from ..registry import ExportRegistry
from .audit_package import AuditPackageProvider
from .common import ExportContext, build_context
from .data_portability import DataPortabilityProvider
from .excel_general import ExcelGeneralProvider
from .group_export import GroupAccessCheck, GroupExportProvider
from .quickbooks_export import QuickBooksExportProvider
from .slsp_summary import SlspSummaryProvider
from .xero_export import XeroExportProvider


def build_default_registry(
    ctx: ExportContext,
    *,
    group_access: GroupAccessCheck | None = None,
    slsp_thresholds=None,
) -> ExportRegistry:
    """The roster a default install registers.

    Providers with an unmet optional dependency are still registered — they report their own
    unavailability at call time rather than being silently absent from the list of formats,
    which is a more honest answer to "what can this install export."
    """
    return ExportRegistry(
        [
            ExcelGeneralProvider(ctx),
            SlspSummaryProvider(ctx, slsp_thresholds),
            AuditPackageProvider(ctx),
            DataPortabilityProvider(ctx),
            GroupExportProvider(ctx, group_access),
            QuickBooksExportProvider(ctx),
            XeroExportProvider(ctx),
        ]
    )


__all__ = [
    "AuditPackageProvider",
    "DataPortabilityProvider",
    "ExcelGeneralProvider",
    "ExportContext",
    "GroupAccessCheck",
    "GroupExportProvider",
    "QuickBooksExportProvider",
    "SlspSummaryProvider",
    "XeroExportProvider",
    "build_context",
    "build_default_registry",
]
