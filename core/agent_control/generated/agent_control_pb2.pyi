from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AgentTokenInfo(_message.Message):
    __slots__ = ("token_id", "issued_by", "issued_to_label", "scopes", "role", "issued_at", "expires_at", "revoked_at", "active")
    TOKEN_ID_FIELD_NUMBER: _ClassVar[int]
    ISSUED_BY_FIELD_NUMBER: _ClassVar[int]
    ISSUED_TO_LABEL_FIELD_NUMBER: _ClassVar[int]
    SCOPES_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    ISSUED_AT_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    REVOKED_AT_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    token_id: str
    issued_by: str
    issued_to_label: str
    scopes: _containers.RepeatedScalarFieldContainer[str]
    role: str
    issued_at: str
    expires_at: str
    revoked_at: str
    active: bool
    def __init__(self, token_id: _Optional[str] = ..., issued_by: _Optional[str] = ..., issued_to_label: _Optional[str] = ..., scopes: _Optional[_Iterable[str]] = ..., role: _Optional[str] = ..., issued_at: _Optional[str] = ..., expires_at: _Optional[str] = ..., revoked_at: _Optional[str] = ..., active: _Optional[bool] = ...) -> None: ...

class IssueTokenRequest(_message.Message):
    __slots__ = ("issued_by", "issued_to_label", "scopes", "role", "expires_in_seconds")
    ISSUED_BY_FIELD_NUMBER: _ClassVar[int]
    ISSUED_TO_LABEL_FIELD_NUMBER: _ClassVar[int]
    SCOPES_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_IN_SECONDS_FIELD_NUMBER: _ClassVar[int]
    issued_by: str
    issued_to_label: str
    scopes: _containers.RepeatedScalarFieldContainer[str]
    role: str
    expires_in_seconds: int
    def __init__(self, issued_by: _Optional[str] = ..., issued_to_label: _Optional[str] = ..., scopes: _Optional[_Iterable[str]] = ..., role: _Optional[str] = ..., expires_in_seconds: _Optional[int] = ...) -> None: ...

class AgentTokenResponse(_message.Message):
    __slots__ = ("token", "plaintext_token", "error_code", "error_detail")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    PLAINTEXT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    token: AgentTokenInfo
    plaintext_token: str
    error_code: str
    error_detail: str
    def __init__(self, token: _Optional[_Union[AgentTokenInfo, _Mapping]] = ..., plaintext_token: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class RevokeTokenRequest(_message.Message):
    __slots__ = ("token_id", "revoked_by")
    TOKEN_ID_FIELD_NUMBER: _ClassVar[int]
    REVOKED_BY_FIELD_NUMBER: _ClassVar[int]
    token_id: str
    revoked_by: str
    def __init__(self, token_id: _Optional[str] = ..., revoked_by: _Optional[str] = ...) -> None: ...

class RevokeResponse(_message.Message):
    __slots__ = ("revoked", "revoked_at", "error_code", "error_detail")
    REVOKED_FIELD_NUMBER: _ClassVar[int]
    REVOKED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    revoked: bool
    revoked_at: str
    error_code: str
    error_detail: str
    def __init__(self, revoked: _Optional[bool] = ..., revoked_at: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListTokensRequest(_message.Message):
    __slots__ = ("include_inactive",)
    INCLUDE_INACTIVE_FIELD_NUMBER: _ClassVar[int]
    include_inactive: bool
    def __init__(self, include_inactive: _Optional[bool] = ...) -> None: ...

class ListTokensResponse(_message.Message):
    __slots__ = ("tokens", "error_code", "error_detail")
    TOKENS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    tokens: _containers.RepeatedCompositeFieldContainer[AgentTokenInfo]
    error_code: str
    error_detail: str
    def __init__(self, tokens: _Optional[_Iterable[_Union[AgentTokenInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class AgentActionRequest(_message.Message):
    __slots__ = ("token", "tool_name", "arguments_json")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_JSON_FIELD_NUMBER: _ClassVar[int]
    token: str
    tool_name: str
    arguments_json: str
    def __init__(self, token: _Optional[str] = ..., tool_name: _Optional[str] = ..., arguments_json: _Optional[str] = ...) -> None: ...

class AgentActionResponse(_message.Message):
    __slots__ = ("ok", "payload_json", "error_code", "error_detail", "tool_category")
    OK_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    TOOL_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    payload_json: str
    error_code: str
    error_detail: str
    tool_category: str
    def __init__(self, ok: _Optional[bool] = ..., payload_json: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., tool_category: _Optional[str] = ...) -> None: ...
