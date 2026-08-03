from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

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
