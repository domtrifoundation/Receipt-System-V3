from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class NotificationMessage(_message.Message):
    __slots__ = ("notification_id", "user_id", "category", "title", "body", "reference", "read_at", "created_at")
    NOTIFICATION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_FIELD_NUMBER: _ClassVar[int]
    READ_AT_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    notification_id: str
    user_id: str
    category: str
    title: str
    body: str
    reference: str
    read_at: str
    created_at: str
    def __init__(self, notification_id: _Optional[str] = ..., user_id: _Optional[str] = ..., category: _Optional[str] = ..., title: _Optional[str] = ..., body: _Optional[str] = ..., reference: _Optional[str] = ..., read_at: _Optional[str] = ..., created_at: _Optional[str] = ...) -> None: ...

class DeliveryStatusMessage(_message.Message):
    __slots__ = ("channel", "outcome", "attempt", "error_detail", "delivered_at")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    DELIVERED_AT_FIELD_NUMBER: _ClassVar[int]
    channel: str
    outcome: str
    attempt: int
    error_detail: str
    delivered_at: str
    def __init__(self, channel: _Optional[str] = ..., outcome: _Optional[str] = ..., attempt: _Optional[int] = ..., error_detail: _Optional[str] = ..., delivered_at: _Optional[str] = ...) -> None: ...

class NotifyRequest(_message.Message):
    __slots__ = ("user_id", "category", "title", "body", "reference")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    category: str
    title: str
    body: str
    reference: str
    def __init__(self, user_id: _Optional[str] = ..., category: _Optional[str] = ..., title: _Optional[str] = ..., body: _Optional[str] = ..., reference: _Optional[str] = ...) -> None: ...

class NotifyResponse(_message.Message):
    __slots__ = ("ok", "notification", "channel_statuses", "error_code", "error_detail")
    OK_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_STATUSES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    notification: NotificationMessage
    channel_statuses: _containers.RepeatedCompositeFieldContainer[DeliveryStatusMessage]
    error_code: str
    error_detail: str
    def __init__(self, ok: _Optional[bool] = ..., notification: _Optional[_Union[NotificationMessage, _Mapping]] = ..., channel_statuses: _Optional[_Iterable[_Union[DeliveryStatusMessage, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class QueryInboxRequest(_message.Message):
    __slots__ = ("user_id", "unread_only", "limit", "offset")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    UNREAD_ONLY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    unread_only: bool
    limit: int
    offset: int
    def __init__(self, user_id: _Optional[str] = ..., unread_only: _Optional[bool] = ..., limit: _Optional[int] = ..., offset: _Optional[int] = ...) -> None: ...

class QueryInboxResponse(_message.Message):
    __slots__ = ("notifications", "total_matching", "error_code", "error_detail")
    NOTIFICATIONS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_MATCHING_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    notifications: _containers.RepeatedCompositeFieldContainer[NotificationMessage]
    total_matching: int
    error_code: str
    error_detail: str
    def __init__(self, notifications: _Optional[_Iterable[_Union[NotificationMessage, _Mapping]]] = ..., total_matching: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class MarkReadRequest(_message.Message):
    __slots__ = ("notification_id",)
    NOTIFICATION_ID_FIELD_NUMBER: _ClassVar[int]
    notification_id: str
    def __init__(self, notification_id: _Optional[str] = ...) -> None: ...

class MarkReadResponse(_message.Message):
    __slots__ = ("ok", "notification_id", "error_code", "error_detail")
    OK_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    notification_id: str
    error_code: str
    error_detail: str
    def __init__(self, ok: _Optional[bool] = ..., notification_id: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class GetPreferencesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ChannelPreferenceMessage(_message.Message):
    __slots__ = ("channel", "enabled", "contact_override")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    CONTACT_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    channel: str
    enabled: bool
    contact_override: str
    def __init__(self, channel: _Optional[str] = ..., enabled: _Optional[bool] = ..., contact_override: _Optional[str] = ...) -> None: ...

class GetPreferencesResponse(_message.Message):
    __slots__ = ("preferences", "error_code", "error_detail")
    PREFERENCES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    preferences: _containers.RepeatedCompositeFieldContainer[ChannelPreferenceMessage]
    error_code: str
    error_detail: str
    def __init__(self, preferences: _Optional[_Iterable[_Union[ChannelPreferenceMessage, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class SetPreferenceRequest(_message.Message):
    __slots__ = ("channel", "enabled", "contact_override")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    CONTACT_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    channel: str
    enabled: bool
    contact_override: str
    def __init__(self, channel: _Optional[str] = ..., enabled: _Optional[bool] = ..., contact_override: _Optional[str] = ...) -> None: ...

class SetPreferenceResponse(_message.Message):
    __slots__ = ("ok", "preference", "error_code", "error_detail")
    OK_FIELD_NUMBER: _ClassVar[int]
    PREFERENCE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    preference: ChannelPreferenceMessage
    error_code: str
    error_detail: str
    def __init__(self, ok: _Optional[bool] = ..., preference: _Optional[_Union[ChannelPreferenceMessage, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
