from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DependencyReachability(_message.Message):
    __slots__ = ("name", "reachable", "checked_at", "latency_ms", "detail")
    NAME_FIELD_NUMBER: _ClassVar[int]
    REACHABLE_FIELD_NUMBER: _ClassVar[int]
    CHECKED_AT_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    name: str
    reachable: bool
    checked_at: str
    latency_ms: float
    detail: str
    def __init__(self, name: _Optional[str] = ..., reachable: _Optional[bool] = ..., checked_at: _Optional[str] = ..., latency_ms: _Optional[float] = ..., detail: _Optional[str] = ...) -> None: ...

class ServiceStatus(_message.Message):
    __slots__ = ("service", "instance_id", "state", "version", "version_commit", "reported_at", "queue_depth", "dependencies", "resource_utilization", "detail")
    class ResourceUtilizationEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    VERSION_COMMIT_FIELD_NUMBER: _ClassVar[int]
    REPORTED_AT_FIELD_NUMBER: _ClassVar[int]
    QUEUE_DEPTH_FIELD_NUMBER: _ClassVar[int]
    DEPENDENCIES_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_UTILIZATION_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    service: str
    instance_id: str
    state: str
    version: str
    version_commit: str
    reported_at: str
    queue_depth: int
    dependencies: _containers.RepeatedCompositeFieldContainer[DependencyReachability]
    resource_utilization: _containers.ScalarMap[str, str]
    detail: str
    def __init__(self, service: _Optional[str] = ..., instance_id: _Optional[str] = ..., state: _Optional[str] = ..., version: _Optional[str] = ..., version_commit: _Optional[str] = ..., reported_at: _Optional[str] = ..., queue_depth: _Optional[int] = ..., dependencies: _Optional[_Iterable[_Union[DependencyReachability, _Mapping]]] = ..., resource_utilization: _Optional[_Mapping[str, str]] = ..., detail: _Optional[str] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ("service", "instance_id")
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    service: str
    instance_id: str
    def __init__(self, service: _Optional[str] = ..., instance_id: _Optional[str] = ...) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("statuses", "error_code", "error_detail")
    STATUSES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    statuses: _containers.RepeatedCompositeFieldContainer[ServiceStatus]
    error_code: str
    error_detail: str
    def __init__(self, statuses: _Optional[_Iterable[_Union[ServiceStatus, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ReportStatusRequest(_message.Message):
    __slots__ = ("status",)
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: ServiceStatus
    def __init__(self, status: _Optional[_Union[ServiceStatus, _Mapping]] = ...) -> None: ...

class ReportStatusAck(_message.Message):
    __slots__ = ("accepted", "error_code", "error_detail")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    error_code: str
    error_detail: str
    def __init__(self, accepted: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ResourceReservation(_message.Message):
    __slots__ = ("reservation_id", "owning_api", "device_id", "reserved_mb", "reserved_at", "expires_at", "released_at", "release_reason")
    RESERVATION_ID_FIELD_NUMBER: _ClassVar[int]
    OWNING_API_FIELD_NUMBER: _ClassVar[int]
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    RESERVED_MB_FIELD_NUMBER: _ClassVar[int]
    RESERVED_AT_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    RELEASED_AT_FIELD_NUMBER: _ClassVar[int]
    RELEASE_REASON_FIELD_NUMBER: _ClassVar[int]
    reservation_id: str
    owning_api: str
    device_id: str
    reserved_mb: int
    reserved_at: str
    expires_at: str
    released_at: str
    release_reason: str
    def __init__(self, reservation_id: _Optional[str] = ..., owning_api: _Optional[str] = ..., device_id: _Optional[str] = ..., reserved_mb: _Optional[int] = ..., reserved_at: _Optional[str] = ..., expires_at: _Optional[str] = ..., released_at: _Optional[str] = ..., release_reason: _Optional[str] = ...) -> None: ...

class ReserveRequest(_message.Message):
    __slots__ = ("owning_api", "device_id", "requested_mb")
    OWNING_API_FIELD_NUMBER: _ClassVar[int]
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_MB_FIELD_NUMBER: _ClassVar[int]
    owning_api: str
    device_id: str
    requested_mb: int
    def __init__(self, owning_api: _Optional[str] = ..., device_id: _Optional[str] = ..., requested_mb: _Optional[int] = ...) -> None: ...

class ReservationResponse(_message.Message):
    __slots__ = ("granted", "reservation", "rejection_reason", "device_total_mb", "device_committed_mb", "error_code", "error_detail")
    GRANTED_FIELD_NUMBER: _ClassVar[int]
    RESERVATION_FIELD_NUMBER: _ClassVar[int]
    REJECTION_REASON_FIELD_NUMBER: _ClassVar[int]
    DEVICE_TOTAL_MB_FIELD_NUMBER: _ClassVar[int]
    DEVICE_COMMITTED_MB_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    granted: bool
    reservation: ResourceReservation
    rejection_reason: str
    device_total_mb: int
    device_committed_mb: int
    error_code: str
    error_detail: str
    def __init__(self, granted: _Optional[bool] = ..., reservation: _Optional[_Union[ResourceReservation, _Mapping]] = ..., rejection_reason: _Optional[str] = ..., device_total_mb: _Optional[int] = ..., device_committed_mb: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ReleaseRequest(_message.Message):
    __slots__ = ("reservation_id", "reason")
    RESERVATION_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    reservation_id: str
    reason: str
    def __init__(self, reservation_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class ReleaseAck(_message.Message):
    __slots__ = ("released", "error_code", "error_detail")
    RELEASED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    released: bool
    error_code: str
    error_detail: str
    def __init__(self, released: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class RefreshRequest(_message.Message):
    __slots__ = ("reservation_id",)
    RESERVATION_ID_FIELD_NUMBER: _ClassVar[int]
    reservation_id: str
    def __init__(self, reservation_id: _Optional[str] = ...) -> None: ...

class CapabilityDriftFinding(_message.Message):
    __slots__ = ("capability", "python_version", "expected_path", "actual_path", "drifted", "detail")
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    PYTHON_VERSION_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_PATH_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_PATH_FIELD_NUMBER: _ClassVar[int]
    DRIFTED_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    capability: str
    python_version: str
    expected_path: str
    actual_path: str
    drifted: bool
    detail: str
    def __init__(self, capability: _Optional[str] = ..., python_version: _Optional[str] = ..., expected_path: _Optional[str] = ..., actual_path: _Optional[str] = ..., drifted: _Optional[bool] = ..., detail: _Optional[str] = ...) -> None: ...

class DriftRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DriftResponse(_message.Message):
    __slots__ = ("findings", "any_drifted", "error_code", "error_detail")
    FINDINGS_FIELD_NUMBER: _ClassVar[int]
    ANY_DRIFTED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    findings: _containers.RepeatedCompositeFieldContainer[CapabilityDriftFinding]
    any_drifted: bool
    error_code: str
    error_detail: str
    def __init__(self, findings: _Optional[_Iterable[_Union[CapabilityDriftFinding, _Mapping]]] = ..., any_drifted: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class LiveDiagnosticFinding(_message.Message):
    __slots__ = ("service", "operation", "baseline_class", "observed_class", "sample_count", "degraded", "detail")
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    BASELINE_CLASS_FIELD_NUMBER: _ClassVar[int]
    OBSERVED_CLASS_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    service: str
    operation: str
    baseline_class: str
    observed_class: str
    sample_count: int
    degraded: bool
    detail: str
    def __init__(self, service: _Optional[str] = ..., operation: _Optional[str] = ..., baseline_class: _Optional[str] = ..., observed_class: _Optional[str] = ..., sample_count: _Optional[int] = ..., degraded: _Optional[bool] = ..., detail: _Optional[str] = ...) -> None: ...

class DiagnosticRequest(_message.Message):
    __slots__ = ("service", "operation")
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    service: str
    operation: str
    def __init__(self, service: _Optional[str] = ..., operation: _Optional[str] = ...) -> None: ...

class DiagnosticResponse(_message.Message):
    __slots__ = ("findings", "error_code", "error_detail")
    FINDINGS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    findings: _containers.RepeatedCompositeFieldContainer[LiveDiagnosticFinding]
    error_code: str
    error_detail: str
    def __init__(self, findings: _Optional[_Iterable[_Union[LiveDiagnosticFinding, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class HeartbeatRequest(_message.Message):
    __slots__ = ("service", "instance_id", "version_commit")
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_COMMIT_FIELD_NUMBER: _ClassVar[int]
    service: str
    instance_id: str
    version_commit: str
    def __init__(self, service: _Optional[str] = ..., instance_id: _Optional[str] = ..., version_commit: _Optional[str] = ...) -> None: ...

class KickAck(_message.Message):
    __slots__ = ("accepted", "kicked_at", "error_code", "error_detail")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    KICKED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    kicked_at: str
    error_code: str
    error_detail: str
    def __init__(self, accepted: _Optional[bool] = ..., kicked_at: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class WatchdogState(_message.Message):
    __slots__ = ("service", "instance_id", "liveness", "last_kick_at", "version_commit", "silent_for_seconds", "timeout_seconds")
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    LIVENESS_FIELD_NUMBER: _ClassVar[int]
    LAST_KICK_AT_FIELD_NUMBER: _ClassVar[int]
    VERSION_COMMIT_FIELD_NUMBER: _ClassVar[int]
    SILENT_FOR_SECONDS_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    service: str
    instance_id: str
    liveness: str
    last_kick_at: str
    version_commit: str
    silent_for_seconds: float
    timeout_seconds: int
    def __init__(self, service: _Optional[str] = ..., instance_id: _Optional[str] = ..., liveness: _Optional[str] = ..., last_kick_at: _Optional[str] = ..., version_commit: _Optional[str] = ..., silent_for_seconds: _Optional[float] = ..., timeout_seconds: _Optional[int] = ...) -> None: ...

class SilenceCheckRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SilentServicesResponse(_message.Message):
    __slots__ = ("states", "silent_services", "checked_at", "error_code", "error_detail")
    STATES_FIELD_NUMBER: _ClassVar[int]
    SILENT_SERVICES_FIELD_NUMBER: _ClassVar[int]
    CHECKED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    states: _containers.RepeatedCompositeFieldContainer[WatchdogState]
    silent_services: _containers.RepeatedScalarFieldContainer[str]
    checked_at: str
    error_code: str
    error_detail: str
    def __init__(self, states: _Optional[_Iterable[_Union[WatchdogState, _Mapping]]] = ..., silent_services: _Optional[_Iterable[str]] = ..., checked_at: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
