from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SubscriptionInfo(_message.Message):
    __slots__ = ("subscription_id", "user_id", "tier", "status", "current_period_end", "created_at", "updated_at")
    SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    TIER_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_PERIOD_END_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    subscription_id: str
    user_id: str
    tier: str
    status: str
    current_period_end: str
    created_at: str
    updated_at: str
    def __init__(self, subscription_id: _Optional[str] = ..., user_id: _Optional[str] = ..., tier: _Optional[str] = ..., status: _Optional[str] = ..., current_period_end: _Optional[str] = ..., created_at: _Optional[str] = ..., updated_at: _Optional[str] = ...) -> None: ...

class CreateSubRequest(_message.Message):
    __slots__ = ("user_id", "tier")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    TIER_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    tier: str
    def __init__(self, user_id: _Optional[str] = ..., tier: _Optional[str] = ...) -> None: ...

class CancelSubRequest(_message.Message):
    __slots__ = ("subscription_id",)
    SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
    subscription_id: str
    def __init__(self, subscription_id: _Optional[str] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ("subscription_id",)
    SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
    subscription_id: str
    def __init__(self, subscription_id: _Optional[str] = ...) -> None: ...

class SubscriptionResponse(_message.Message):
    __slots__ = ("subscription", "error_code", "error_detail")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    subscription: SubscriptionInfo
    error_code: str
    error_detail: str
    def __init__(self, subscription: _Optional[_Union[SubscriptionInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class WebhookPayload(_message.Message):
    __slots__ = ("payload", "signature")
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    payload: bytes
    signature: str
    def __init__(self, payload: _Optional[bytes] = ..., signature: _Optional[str] = ...) -> None: ...

class WebhookAck(_message.Message):
    __slots__ = ("accepted", "verified", "error_code", "error_detail")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    VERIFIED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    verified: bool
    error_code: str
    error_detail: str
    def __init__(self, accepted: _Optional[bool] = ..., verified: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
