from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StepResultInfo(_message.Message):
    __slots__ = ("kind", "from_version", "to_version", "description", "outcome", "started_at", "finished_at", "error_code", "error_detail")
    KIND_FIELD_NUMBER: _ClassVar[int]
    FROM_VERSION_FIELD_NUMBER: _ClassVar[int]
    TO_VERSION_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    FINISHED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    kind: str
    from_version: int
    to_version: int
    description: str
    outcome: str
    started_at: str
    finished_at: str
    error_code: str
    error_detail: str
    def __init__(self, kind: _Optional[str] = ..., from_version: _Optional[int] = ..., to_version: _Optional[int] = ..., description: _Optional[str] = ..., outcome: _Optional[str] = ..., started_at: _Optional[str] = ..., finished_at: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class MigrationRequest(_message.Message):
    __slots__ = ("structure_id", "kind", "current_version", "target_version")
    STRUCTURE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CURRENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    TARGET_VERSION_FIELD_NUMBER: _ClassVar[int]
    structure_id: str
    kind: str
    current_version: int
    target_version: int
    def __init__(self, structure_id: _Optional[str] = ..., kind: _Optional[str] = ..., current_version: _Optional[int] = ..., target_version: _Optional[int] = ...) -> None: ...

class MigrationResponse(_message.Message):
    __slots__ = ("structure_id", "kind", "from_version", "reached_version", "target_version", "steps", "error_code", "error_detail")
    STRUCTURE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    FROM_VERSION_FIELD_NUMBER: _ClassVar[int]
    REACHED_VERSION_FIELD_NUMBER: _ClassVar[int]
    TARGET_VERSION_FIELD_NUMBER: _ClassVar[int]
    STEPS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    structure_id: str
    kind: str
    from_version: int
    reached_version: int
    target_version: int
    steps: _containers.RepeatedCompositeFieldContainer[StepResultInfo]
    error_code: str
    error_detail: str
    def __init__(self, structure_id: _Optional[str] = ..., kind: _Optional[str] = ..., from_version: _Optional[int] = ..., reached_version: _Optional[int] = ..., target_version: _Optional[int] = ..., steps: _Optional[_Iterable[_Union[StepResultInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class VersionRequest(_message.Message):
    __slots__ = ("kind",)
    KIND_FIELD_NUMBER: _ClassVar[int]
    kind: str
    def __init__(self, kind: _Optional[str] = ...) -> None: ...

class VersionResponse(_message.Message):
    __slots__ = ("kind", "current_version", "error_code", "error_detail")
    KIND_FIELD_NUMBER: _ClassVar[int]
    CURRENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    kind: str
    current_version: int
    error_code: str
    error_detail: str
    def __init__(self, kind: _Optional[str] = ..., current_version: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
