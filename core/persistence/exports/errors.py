"""Export Framework error codes."""

from __future__ import annotations

UNKNOWN_PROVIDER = "export_unknown_provider"
PROVIDER_UNAVAILABLE = "export_provider_unavailable"
GENERATION_FAILED = "export_generation_failed"
NO_DATA_IN_SCOPE = "export_no_data_in_scope"
ACCESS_DENIED = "export_access_denied"
SPEC_UNAVAILABLE = "export_spec_unavailable"
ARCHIVE_CHECK_FAILED = "export_archive_check_failed"


class ExportError(Exception):
    code = GENERATION_FAILED


class UnknownProvider(ExportError):
    code = UNKNOWN_PROVIDER


class ProviderUnavailable(ExportError):
    """A provider whose optional dependency is missing — `openpyxl`, most often.

    A degradation, never a crash: the provider reports itself unavailable and every other
    registered provider keeps working (`docs/PRINCIPLES.md` §4.4).
    """

    code = PROVIDER_UNAVAILABLE


class SpecUnavailable(ExportError):
    """The output format's own specification is not settled enough to generate.

    This exists for one real, documented case: the BIR SLSP DAT file's byte-level
    field-order/delimiter specification is genuinely not publicly available — a
    Freedom-of-Information request for RMC-24-2002's Annexes A–F was denied. Emitting a
    guessed layout for a tax submission would be worse than emitting nothing, so the
    provider refuses that artifact and still produces the reviewable `.xlsx`.
    """

    code = SPEC_UNAVAILABLE


__all__ = [
    "ACCESS_DENIED",
    "ARCHIVE_CHECK_FAILED",
    "GENERATION_FAILED",
    "NO_DATA_IN_SCOPE",
    "PROVIDER_UNAVAILABLE",
    "SPEC_UNAVAILABLE",
    "UNKNOWN_PROVIDER",
    "ExportError",
    "ProviderUnavailable",
    "SpecUnavailable",
    "UnknownProvider",
]
