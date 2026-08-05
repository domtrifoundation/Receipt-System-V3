from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DetectAndFileIssuesRequest(_message.Message):
    __slots__ = ("install_root", "health_address")
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    HEALTH_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    health_address: str
    def __init__(self, install_root: _Optional[str] = ..., health_address: _Optional[str] = ...) -> None: ...

class DetectAndFileIssuesResponse(_message.Message):
    __slots__ = ("filed", "known")
    FILED_FIELD_NUMBER: _ClassVar[int]
    KNOWN_FIELD_NUMBER: _ClassVar[int]
    filed: _containers.RepeatedCompositeFieldContainer[FiledIssueStatus]
    known: bool
    def __init__(self, filed: _Optional[_Iterable[_Union[FiledIssueStatus, _Mapping]]] = ..., known: _Optional[bool] = ...) -> None: ...

class RecordFiledIssueRequest(_message.Message):
    __slots__ = ("install_root", "fingerprint", "issue_number", "url", "title")
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    ISSUE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    fingerprint: str
    issue_number: int
    url: str
    title: str
    def __init__(self, install_root: _Optional[str] = ..., fingerprint: _Optional[str] = ..., issue_number: _Optional[int] = ..., url: _Optional[str] = ..., title: _Optional[str] = ...) -> None: ...

class RecordFiledIssueResponse(_message.Message):
    __slots__ = ("known",)
    KNOWN_FIELD_NUMBER: _ClassVar[int]
    known: bool
    def __init__(self, known: _Optional[bool] = ...) -> None: ...

class ListFiledIssuesRequest(_message.Message):
    __slots__ = ("install_root",)
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    def __init__(self, install_root: _Optional[str] = ...) -> None: ...

class FiledIssueStatus(_message.Message):
    __slots__ = ("issue_number", "title", "url", "filed_at", "state", "linked_pr_numbers", "checked_at", "error_detail")
    ISSUE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    FILED_AT_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    LINKED_PR_NUMBERS_FIELD_NUMBER: _ClassVar[int]
    CHECKED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    issue_number: int
    title: str
    url: str
    filed_at: str
    state: str
    linked_pr_numbers: _containers.RepeatedScalarFieldContainer[int]
    checked_at: str
    error_detail: str
    def __init__(self, issue_number: _Optional[int] = ..., title: _Optional[str] = ..., url: _Optional[str] = ..., filed_at: _Optional[str] = ..., state: _Optional[str] = ..., linked_pr_numbers: _Optional[_Iterable[int]] = ..., checked_at: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListFiledIssuesResponse(_message.Message):
    __slots__ = ("issues", "known")
    ISSUES_FIELD_NUMBER: _ClassVar[int]
    KNOWN_FIELD_NUMBER: _ClassVar[int]
    issues: _containers.RepeatedCompositeFieldContainer[FiledIssueStatus]
    known: bool
    def __init__(self, issues: _Optional[_Iterable[_Union[FiledIssueStatus, _Mapping]]] = ..., known: _Optional[bool] = ...) -> None: ...

class OptInConfigRequest(_message.Message):
    __slots__ = ("install_root",)
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    def __init__(self, install_root: _Optional[str] = ...) -> None: ...

class OptInResponse(_message.Message):
    __slots__ = ("opt_in", "known")
    OPT_IN_FIELD_NUMBER: _ClassVar[int]
    KNOWN_FIELD_NUMBER: _ClassVar[int]
    opt_in: bool
    known: bool
    def __init__(self, opt_in: _Optional[bool] = ..., known: _Optional[bool] = ...) -> None: ...

class SetOptInRequest(_message.Message):
    __slots__ = ("install_root", "opt_in")
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    OPT_IN_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    opt_in: bool
    def __init__(self, install_root: _Optional[str] = ..., opt_in: _Optional[bool] = ...) -> None: ...

class TrackedDependencyInfo(_message.Message):
    __slots__ = ("name", "fact_kinds", "upstream_issue_refs", "source_deep_dive", "notes")
    NAME_FIELD_NUMBER: _ClassVar[int]
    FACT_KINDS_FIELD_NUMBER: _ClassVar[int]
    UPSTREAM_ISSUE_REFS_FIELD_NUMBER: _ClassVar[int]
    SOURCE_DEEP_DIVE_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    name: str
    fact_kinds: _containers.RepeatedScalarFieldContainer[str]
    upstream_issue_refs: _containers.RepeatedScalarFieldContainer[str]
    source_deep_dive: str
    notes: str
    def __init__(self, name: _Optional[str] = ..., fact_kinds: _Optional[_Iterable[str]] = ..., upstream_issue_refs: _Optional[_Iterable[str]] = ..., source_deep_dive: _Optional[str] = ..., notes: _Optional[str] = ...) -> None: ...

class TrackedDepsRequest(_message.Message):
    __slots__ = ("fact_kind",)
    FACT_KIND_FIELD_NUMBER: _ClassVar[int]
    fact_kind: str
    def __init__(self, fact_kind: _Optional[str] = ...) -> None: ...

class TrackedDepsResponse(_message.Message):
    __slots__ = ("dependencies", "error_code", "error_detail")
    DEPENDENCIES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    dependencies: _containers.RepeatedCompositeFieldContainer[TrackedDependencyInfo]
    error_code: str
    error_detail: str
    def __init__(self, dependencies: _Optional[_Iterable[_Union[TrackedDependencyInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ChangelogRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ChangelogResponse(_message.Message):
    __slots__ = ("markdown", "error_code", "error_detail")
    MARKDOWN_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    markdown: str
    error_code: str
    error_detail: str
    def __init__(self, markdown: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
