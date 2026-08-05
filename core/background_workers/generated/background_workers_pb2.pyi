from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class JobRegistrationInfo(_message.Message):
    __slots__ = ("job_id", "owning_api", "job_class", "idle_only", "event_triggered", "interval_seconds", "scope", "description")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    OWNING_API_FIELD_NUMBER: _ClassVar[int]
    JOB_CLASS_FIELD_NUMBER: _ClassVar[int]
    IDLE_ONLY_FIELD_NUMBER: _ClassVar[int]
    EVENT_TRIGGERED_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    owning_api: str
    job_class: str
    idle_only: bool
    event_triggered: bool
    interval_seconds: int
    scope: str
    description: str
    def __init__(self, job_id: _Optional[str] = ..., owning_api: _Optional[str] = ..., job_class: _Optional[str] = ..., idle_only: _Optional[bool] = ..., event_triggered: _Optional[bool] = ..., interval_seconds: _Optional[int] = ..., scope: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...

class JobHealthInfo(_message.Message):
    __slots__ = ("job_id", "consecutive_failures", "total_runs", "total_failures", "last_run_at", "last_outcome", "last_error_detail", "disabled_at", "disabled_reason")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    CONSECUTIVE_FAILURES_FIELD_NUMBER: _ClassVar[int]
    TOTAL_RUNS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FAILURES_FIELD_NUMBER: _ClassVar[int]
    LAST_RUN_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_OUTCOME_FIELD_NUMBER: _ClassVar[int]
    LAST_ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    DISABLED_AT_FIELD_NUMBER: _ClassVar[int]
    DISABLED_REASON_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    consecutive_failures: int
    total_runs: int
    total_failures: int
    last_run_at: str
    last_outcome: str
    last_error_detail: str
    disabled_at: str
    disabled_reason: str
    def __init__(self, job_id: _Optional[str] = ..., consecutive_failures: _Optional[int] = ..., total_runs: _Optional[int] = ..., total_failures: _Optional[int] = ..., last_run_at: _Optional[str] = ..., last_outcome: _Optional[str] = ..., last_error_detail: _Optional[str] = ..., disabled_at: _Optional[str] = ..., disabled_reason: _Optional[str] = ...) -> None: ...

class ListJobsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListJobsResponse(_message.Message):
    __slots__ = ("jobs", "error_code", "error_detail")
    JOBS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    jobs: _containers.RepeatedCompositeFieldContainer[JobRegistrationInfo]
    error_code: str
    error_detail: str
    def __init__(self, jobs: _Optional[_Iterable[_Union[JobRegistrationInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class JobHealthRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class JobHealthResponse(_message.Message):
    __slots__ = ("health", "error_code", "error_detail")
    HEALTH_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    health: JobHealthInfo
    error_code: str
    error_detail: str
    def __init__(self, health: _Optional[_Union[JobHealthInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class EnableJobRequest(_message.Message):
    __slots__ = ("session_id", "job_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    job_id: str
    def __init__(self, session_id: _Optional[str] = ..., job_id: _Optional[str] = ...) -> None: ...

class NextDueRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class NextDueEstimateInfo(_message.Message):
    __slots__ = ("job_id", "seconds_until_due", "approximate", "blocked_by_idle")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    SECONDS_UNTIL_DUE_FIELD_NUMBER: _ClassVar[int]
    APPROXIMATE_FIELD_NUMBER: _ClassVar[int]
    BLOCKED_BY_IDLE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    seconds_until_due: float
    approximate: bool
    blocked_by_idle: bool
    def __init__(self, job_id: _Optional[str] = ..., seconds_until_due: _Optional[float] = ..., approximate: _Optional[bool] = ..., blocked_by_idle: _Optional[bool] = ...) -> None: ...

class NextDueResponse(_message.Message):
    __slots__ = ("estimates", "error_code", "error_detail")
    ESTIMATES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    estimates: _containers.RepeatedCompositeFieldContainer[NextDueEstimateInfo]
    error_code: str
    error_detail: str
    def __init__(self, estimates: _Optional[_Iterable[_Union[NextDueEstimateInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
