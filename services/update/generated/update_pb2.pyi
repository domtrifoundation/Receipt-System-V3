from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CloneRequest(_message.Message):
    __slots__ = ("install_root", "channel", "ref_override", "license_key", "instance_id", "dev_mode_set", "dev_mode", "python_bin")
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    REF_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    LICENSE_KEY_FIELD_NUMBER: _ClassVar[int]
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    DEV_MODE_SET_FIELD_NUMBER: _ClassVar[int]
    DEV_MODE_FIELD_NUMBER: _ClassVar[int]
    PYTHON_BIN_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    channel: str
    ref_override: str
    license_key: str
    instance_id: str
    dev_mode_set: bool
    dev_mode: bool
    python_bin: str
    def __init__(self, install_root: _Optional[str] = ..., channel: _Optional[str] = ..., ref_override: _Optional[str] = ..., license_key: _Optional[str] = ..., instance_id: _Optional[str] = ..., dev_mode_set: _Optional[bool] = ..., dev_mode: _Optional[bool] = ..., python_bin: _Optional[str] = ...) -> None: ...

class ReleaseDirectoryResponse(_message.Message):
    __slots__ = ("ok", "path", "version", "commit_hash", "ref", "channel", "used_fallback_ref", "keymaster_token_used", "finalize_ok", "error_code", "error_detail")
    OK_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    COMMIT_HASH_FIELD_NUMBER: _ClassVar[int]
    REF_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    USED_FALLBACK_REF_FIELD_NUMBER: _ClassVar[int]
    KEYMASTER_TOKEN_USED_FIELD_NUMBER: _ClassVar[int]
    FINALIZE_OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    path: str
    version: str
    commit_hash: str
    ref: str
    channel: str
    used_fallback_ref: bool
    keymaster_token_used: bool
    finalize_ok: bool
    error_code: str
    error_detail: str
    def __init__(self, ok: _Optional[bool] = ..., path: _Optional[str] = ..., version: _Optional[str] = ..., commit_hash: _Optional[str] = ..., ref: _Optional[str] = ..., channel: _Optional[str] = ..., used_fallback_ref: _Optional[bool] = ..., keymaster_token_used: _Optional[bool] = ..., finalize_ok: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ChannelRequest(_message.Message):
    __slots__ = ("install_root",)
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    def __init__(self, install_root: _Optional[str] = ...) -> None: ...

class ChannelUsageInfo(_message.Message):
    __slots__ = ("channel", "last_release_name", "last_cloned_at")
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    LAST_RELEASE_NAME_FIELD_NUMBER: _ClassVar[int]
    LAST_CLONED_AT_FIELD_NUMBER: _ClassVar[int]
    channel: str
    last_release_name: str
    last_cloned_at: str
    def __init__(self, channel: _Optional[str] = ..., last_release_name: _Optional[str] = ..., last_cloned_at: _Optional[str] = ...) -> None: ...

class ChannelListResponse(_message.Message):
    __slots__ = ("channels", "error_code", "error_detail")
    CHANNELS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    channels: _containers.RepeatedCompositeFieldContainer[ChannelUsageInfo]
    error_code: str
    error_detail: str
    def __init__(self, channels: _Optional[_Iterable[_Union[ChannelUsageInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
