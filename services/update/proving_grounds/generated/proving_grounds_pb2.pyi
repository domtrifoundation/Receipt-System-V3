from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TestCandidateRequest(_message.Message):
    __slots__ = ("kind", "name", "version", "affected_api", "download_url", "hf_token", "requested_by")
    KIND_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    AFFECTED_API_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_URL_FIELD_NUMBER: _ClassVar[int]
    HF_TOKEN_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_BY_FIELD_NUMBER: _ClassVar[int]
    kind: str
    name: str
    version: str
    affected_api: str
    download_url: str
    hf_token: str
    requested_by: str
    def __init__(self, kind: _Optional[str] = ..., name: _Optional[str] = ..., version: _Optional[str] = ..., affected_api: _Optional[str] = ..., download_url: _Optional[str] = ..., hf_token: _Optional[str] = ..., requested_by: _Optional[str] = ...) -> None: ...

class TestResultInfo(_message.Message):
    __slots__ = ("candidate_name", "candidate_version", "affected_api", "passed", "started_at", "finished_at", "bench_summary", "error_code", "error_detail")
    CANDIDATE_NAME_FIELD_NUMBER: _ClassVar[int]
    CANDIDATE_VERSION_FIELD_NUMBER: _ClassVar[int]
    AFFECTED_API_FIELD_NUMBER: _ClassVar[int]
    PASSED_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    FINISHED_AT_FIELD_NUMBER: _ClassVar[int]
    BENCH_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    candidate_name: str
    candidate_version: str
    affected_api: str
    passed: bool
    started_at: str
    finished_at: str
    bench_summary: str
    error_code: str
    error_detail: str
    def __init__(self, candidate_name: _Optional[str] = ..., candidate_version: _Optional[str] = ..., affected_api: _Optional[str] = ..., passed: _Optional[bool] = ..., started_at: _Optional[str] = ..., finished_at: _Optional[str] = ..., bench_summary: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class TestResultResponse(_message.Message):
    __slots__ = ("result", "error_code", "error_detail")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    result: TestResultInfo
    error_code: str
    error_detail: str
    def __init__(self, result: _Optional[_Union[TestResultInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class HistoryRequest(_message.Message):
    __slots__ = ("affected_api", "limit")
    AFFECTED_API_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    affected_api: str
    limit: int
    def __init__(self, affected_api: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class TestHistoryResponse(_message.Message):
    __slots__ = ("results", "error_code", "error_detail")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[TestResultInfo]
    error_code: str
    error_detail: str
    def __init__(self, results: _Optional[_Iterable[_Union[TestResultInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
