from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RunChecksRequest(_message.Message):
    __slots__ = ("receipt_id", "check_names")
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    CHECK_NAMES_FIELD_NUMBER: _ClassVar[int]
    receipt_id: str
    check_names: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, receipt_id: _Optional[str] = ..., check_names: _Optional[_Iterable[str]] = ...) -> None: ...

class CheckResult(_message.Message):
    __slots__ = ("check_name", "flag_type", "severity", "outcome", "detail")
    CHECK_NAME_FIELD_NUMBER: _ClassVar[int]
    FLAG_TYPE_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    check_name: str
    flag_type: str
    severity: str
    outcome: str
    detail: str
    def __init__(self, check_name: _Optional[str] = ..., flag_type: _Optional[str] = ..., severity: _Optional[str] = ..., outcome: _Optional[str] = ..., detail: _Optional[str] = ...) -> None: ...

class RunChecksResponse(_message.Message):
    __slots__ = ("results", "error_code", "error_detail")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[CheckResult]
    error_code: str
    error_detail: str
    def __init__(self, results: _Optional[_Iterable[_Union[CheckResult, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class PropagateRequest(_message.Message):
    __slots__ = ("entity_type", "entity_id", "change")
    class ChangeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ENTITY_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENTITY_ID_FIELD_NUMBER: _ClassVar[int]
    CHANGE_FIELD_NUMBER: _ClassVar[int]
    entity_type: str
    entity_id: str
    change: _containers.ScalarMap[str, str]
    def __init__(self, entity_type: _Optional[str] = ..., entity_id: _Optional[str] = ..., change: _Optional[_Mapping[str, str]] = ...) -> None: ...

class PropagationJobResponse(_message.Message):
    __slots__ = ("job_id", "receipts_total", "receipts_propagated", "receipts_resumed", "conflicted_receipt_ids", "error_code", "error_detail")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPTS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    RECEIPTS_PROPAGATED_FIELD_NUMBER: _ClassVar[int]
    RECEIPTS_RESUMED_FIELD_NUMBER: _ClassVar[int]
    CONFLICTED_RECEIPT_IDS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    receipts_total: int
    receipts_propagated: int
    receipts_resumed: int
    conflicted_receipt_ids: _containers.RepeatedScalarFieldContainer[str]
    error_code: str
    error_detail: str
    def __init__(self, job_id: _Optional[str] = ..., receipts_total: _Optional[int] = ..., receipts_propagated: _Optional[int] = ..., receipts_resumed: _Optional[int] = ..., conflicted_receipt_ids: _Optional[_Iterable[str]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
