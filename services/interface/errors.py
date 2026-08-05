"""Interface API errors (`docs/PRINCIPLES.md` §4.1 — errors are data, never raised across
a gRPC boundary; Interface has no gRPC boundary of its own beyond `GetMenuTree`, so these
are internal-use only, surfaced to the operator as plain screen text)."""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class InterfaceInternalError(Exception):
    """Base for this package's internal error types."""


class UnresolvedMenuTarget(InterfaceInternalError):
    """A `MenuItemSpec.target` does not resolve to a currently-registered API call."""


class SettingNotFound(InterfaceInternalError):
    """`find_setting` found no match, not even a fuzzy or `former_paths` one."""


ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnresolvedMenuTarget: "UNRESOLVED_MENU_TARGET",
        SettingNotFound: "SETTING_NOT_FOUND",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNRESOLVED_MENU_TARGET": "This menu entry points at an API call that isn't registered.",
        "SETTING_NOT_FOUND": "No setting matched that search, even with fuzzy matching.",
    }
)


def code_for(exc: InterfaceInternalError) -> str:
    return ERROR_CODES.get(type(exc), "UNKNOWN_INTERFACE_ERROR")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, "An unrecognized Interface API error occurred.")


__all__ = [
    "InterfaceInternalError",
    "UnresolvedMenuTarget",
    "SettingNotFound",
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "code_for",
    "summary_for",
]
