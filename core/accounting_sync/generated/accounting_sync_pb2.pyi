from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class InitiateAuthRequest(_message.Message):
    __slots__ = ("user_id", "provider")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider: str
    def __init__(self, user_id: _Optional[str] = ..., provider: _Optional[str] = ...) -> None: ...

class InitiateAuthResponse(_message.Message):
    __slots__ = ("url", "state", "error_code", "error_detail")
    URL_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    url: str
    state: str
    error_code: str
    error_detail: str
    def __init__(self, url: _Optional[str] = ..., state: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class CompleteAuthRequest(_message.Message):
    __slots__ = ("user_id", "provider", "callback_params")
    class CallbackParamsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    CALLBACK_PARAMS_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider: str
    callback_params: _containers.ScalarMap[str, str]
    def __init__(self, user_id: _Optional[str] = ..., provider: _Optional[str] = ..., callback_params: _Optional[_Mapping[str, str]] = ...) -> None: ...

class CompleteAuthResponse(_message.Message):
    __slots__ = ("external_account_id", "error_code", "error_detail")
    EXTERNAL_ACCOUNT_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    external_account_id: str
    error_code: str
    error_detail: str
    def __init__(self, external_account_id: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class SyncStatusRequest(_message.Message):
    __slots__ = ("user_id", "provider")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider: str
    def __init__(self, user_id: _Optional[str] = ..., provider: _Optional[str] = ...) -> None: ...

class SyncStatusResponse(_message.Message):
    __slots__ = ("connected",)
    CONNECTED_FIELD_NUMBER: _ClassVar[int]
    connected: bool
    def __init__(self, connected: _Optional[bool] = ...) -> None: ...

class DisconnectRequest(_message.Message):
    __slots__ = ("user_id", "provider")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider: str
    def __init__(self, user_id: _Optional[str] = ..., provider: _Optional[str] = ...) -> None: ...

class DisconnectResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class PushReceiptRequest(_message.Message):
    __slots__ = ("user_id", "provider", "receipt_id", "vendor_display_name")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    VENDOR_DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider: str
    receipt_id: str
    vendor_display_name: str
    def __init__(self, user_id: _Optional[str] = ..., provider: _Optional[str] = ..., receipt_id: _Optional[str] = ..., vendor_display_name: _Optional[str] = ...) -> None: ...

class PushReceiptResponse(_message.Message):
    __slots__ = ("external_record_id", "error_code", "error_detail")
    EXTERNAL_RECORD_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    external_record_id: str
    error_code: str
    error_detail: str
    def __init__(self, external_record_id: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
