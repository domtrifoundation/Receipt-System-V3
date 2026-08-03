from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChannelRequest(_message.Message):
    __slots__ = ("channel",)
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    channel: str
    def __init__(self, channel: _Optional[str] = ...) -> None: ...

class ActiveReleaseResponse(_message.Message):
    __slots__ = ("channel", "release_dir", "activated_at", "error_code", "error_detail")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    RELEASE_DIR_FIELD_NUMBER: _ClassVar[int]
    ACTIVATED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    channel: str
    release_dir: str
    activated_at: str
    error_code: str
    error_detail: str
    def __init__(self, channel: _Optional[str] = ..., release_dir: _Optional[str] = ..., activated_at: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class RollbackRequest(_message.Message):
    __slots__ = ("channel",)
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    channel: str
    def __init__(self, channel: _Optional[str] = ...) -> None: ...

class RollbackResponse(_message.Message):
    __slots__ = ("channel", "reverted_to", "ok", "error_code", "error_detail")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    REVERTED_TO_FIELD_NUMBER: _ClassVar[int]
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    channel: str
    reverted_to: str
    ok: bool
    error_code: str
    error_detail: str
    def __init__(self, channel: _Optional[str] = ..., reverted_to: _Optional[str] = ..., ok: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ServiceStatusRequest(_message.Message):
    __slots__ = ("service_name",)
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    def __init__(self, service_name: _Optional[str] = ...) -> None: ...

class SleepStatusResponse(_message.Message):
    __slots__ = ("service_name", "policy", "state", "last_activity_at")
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    POLICY_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    LAST_ACTIVITY_AT_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    policy: str
    state: str
    last_activity_at: str
    def __init__(self, service_name: _Optional[str] = ..., policy: _Optional[str] = ..., state: _Optional[str] = ..., last_activity_at: _Optional[str] = ...) -> None: ...

class ForceWakeRequest(_message.Message):
    __slots__ = ("service_name", "requested_by")
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_BY_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    requested_by: str
    def __init__(self, service_name: _Optional[str] = ..., requested_by: _Optional[str] = ...) -> None: ...

class WakeResponse(_message.Message):
    __slots__ = ("woke", "error_code", "error_detail")
    WOKE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    woke: bool
    error_code: str
    error_detail: str
    def __init__(self, woke: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class PinRequest(_message.Message):
    __slots__ = ("channel", "service_name", "pinned_version", "pinned_by")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    PINNED_VERSION_FIELD_NUMBER: _ClassVar[int]
    PINNED_BY_FIELD_NUMBER: _ClassVar[int]
    channel: str
    service_name: str
    pinned_version: str
    pinned_by: str
    def __init__(self, channel: _Optional[str] = ..., service_name: _Optional[str] = ..., pinned_version: _Optional[str] = ..., pinned_by: _Optional[str] = ...) -> None: ...

class ServiceVersionPinResponse(_message.Message):
    __slots__ = ("channel", "service_name", "pinned_version", "pinned_by", "pinned_at")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    PINNED_VERSION_FIELD_NUMBER: _ClassVar[int]
    PINNED_BY_FIELD_NUMBER: _ClassVar[int]
    PINNED_AT_FIELD_NUMBER: _ClassVar[int]
    channel: str
    service_name: str
    pinned_version: str
    pinned_by: str
    pinned_at: str
    def __init__(self, channel: _Optional[str] = ..., service_name: _Optional[str] = ..., pinned_version: _Optional[str] = ..., pinned_by: _Optional[str] = ..., pinned_at: _Optional[str] = ...) -> None: ...

class PinListResponse(_message.Message):
    __slots__ = ("pins",)
    PINS_FIELD_NUMBER: _ClassVar[int]
    pins: _containers.RepeatedCompositeFieldContainer[ServiceVersionPinResponse]
    def __init__(self, pins: _Optional[_Iterable[_Union[ServiceVersionPinResponse, _Mapping]]] = ...) -> None: ...

class RestartRequest(_message.Message):
    __slots__ = ("service_name", "target_version")
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    TARGET_VERSION_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    target_version: str
    def __init__(self, service_name: _Optional[str] = ..., target_version: _Optional[str] = ...) -> None: ...

class RestartProgress(_message.Message):
    __slots__ = ("service_name", "target_version", "stage", "error_detail")
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    TARGET_VERSION_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    target_version: str
    stage: str
    error_detail: str
    def __init__(self, service_name: _Optional[str] = ..., target_version: _Optional[str] = ..., stage: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
