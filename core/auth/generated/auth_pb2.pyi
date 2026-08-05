from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TenancyConfigRequest(_message.Message):
    __slots__ = ("install_root",)
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    def __init__(self, install_root: _Optional[str] = ...) -> None: ...

class TenancyModeResponse(_message.Message):
    __slots__ = ("tenancy_mode", "known", "takes_effect_on_restart")
    TENANCY_MODE_FIELD_NUMBER: _ClassVar[int]
    KNOWN_FIELD_NUMBER: _ClassVar[int]
    TAKES_EFFECT_ON_RESTART_FIELD_NUMBER: _ClassVar[int]
    tenancy_mode: str
    known: bool
    takes_effect_on_restart: bool
    def __init__(self, tenancy_mode: _Optional[str] = ..., known: _Optional[bool] = ..., takes_effect_on_restart: _Optional[bool] = ...) -> None: ...

class SetTenancyModeRequest(_message.Message):
    __slots__ = ("install_root", "tenancy_mode")
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    TENANCY_MODE_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    tenancy_mode: str
    def __init__(self, install_root: _Optional[str] = ..., tenancy_mode: _Optional[str] = ...) -> None: ...

class SessionResponse(_message.Message):
    __slots__ = ("session_id", "user_id", "role", "expires_at_unix", "error_code", "csrf_token", "second_factor_challenge_id", "second_factor_method", "error_detail")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    CSRF_TOKEN_FIELD_NUMBER: _ClassVar[int]
    SECOND_FACTOR_CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    SECOND_FACTOR_METHOD_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    user_id: str
    role: str
    expires_at_unix: int
    error_code: str
    csrf_token: str
    second_factor_challenge_id: str
    second_factor_method: str
    error_detail: str
    def __init__(self, session_id: _Optional[str] = ..., user_id: _Optional[str] = ..., role: _Optional[str] = ..., expires_at_unix: _Optional[int] = ..., error_code: _Optional[str] = ..., csrf_token: _Optional[str] = ..., second_factor_challenge_id: _Optional[str] = ..., second_factor_method: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class InitiateLoginRequest(_message.Message):
    __slots__ = ("provider",)
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    provider: str
    def __init__(self, provider: _Optional[str] = ...) -> None: ...

class InitiateLoginResponse(_message.Message):
    __slots__ = ("challenge_id", "redirect_url", "state", "error_code", "error_detail")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    REDIRECT_URL_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    redirect_url: str
    state: str
    error_code: str
    error_detail: str
    def __init__(self, challenge_id: _Optional[str] = ..., redirect_url: _Optional[str] = ..., state: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class CompleteLoginRequest(_message.Message):
    __slots__ = ("challenge_id", "callback", "second_factor_code")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    CALLBACK_FIELD_NUMBER: _ClassVar[int]
    SECOND_FACTOR_CODE_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    callback: str
    second_factor_code: str
    def __init__(self, challenge_id: _Optional[str] = ..., callback: _Optional[str] = ..., second_factor_code: _Optional[str] = ...) -> None: ...

class RegisterPasskeyRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class RegisterPasskeyResponse(_message.Message):
    __slots__ = ("challenge_id", "options_json", "credential_id", "error_code", "error_detail")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_JSON_FIELD_NUMBER: _ClassVar[int]
    CREDENTIAL_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    options_json: str
    credential_id: str
    error_code: str
    error_detail: str
    def __init__(self, challenge_id: _Optional[str] = ..., options_json: _Optional[str] = ..., credential_id: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class PasskeyLoginRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class PasskeyChallengeResponse(_message.Message):
    __slots__ = ("challenge_id", "options_json", "error_code", "error_detail")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    options_json: str
    error_code: str
    error_detail: str
    def __init__(self, challenge_id: _Optional[str] = ..., options_json: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class PasskeyAssertionRequest(_message.Message):
    __slots__ = ("challenge_id", "assertion_json", "second_factor_code")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    ASSERTION_JSON_FIELD_NUMBER: _ClassVar[int]
    SECOND_FACTOR_CODE_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    assertion_json: str
    second_factor_code: str
    def __init__(self, challenge_id: _Optional[str] = ..., assertion_json: _Optional[str] = ..., second_factor_code: _Optional[str] = ...) -> None: ...

class EmailLoginRequest(_message.Message):
    __slots__ = ("email",)
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    email: str
    def __init__(self, email: _Optional[str] = ...) -> None: ...

class SmsLoginRequest(_message.Message):
    __slots__ = ("phone_number",)
    PHONE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    phone_number: str
    def __init__(self, phone_number: _Optional[str] = ...) -> None: ...

class OtpSentResponse(_message.Message):
    __slots__ = ("challenge_id", "channel", "code_length", "expires_at_unix", "error_code", "error_detail")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    CODE_LENGTH_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    channel: str
    code_length: int
    expires_at_unix: int
    error_code: str
    error_detail: str
    def __init__(self, challenge_id: _Optional[str] = ..., channel: _Optional[str] = ..., code_length: _Optional[int] = ..., expires_at_unix: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class OtpVerifyRequest(_message.Message):
    __slots__ = ("challenge_id", "code", "second_factor_code")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    SECOND_FACTOR_CODE_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    code: str
    second_factor_code: str
    def __init__(self, challenge_id: _Optional[str] = ..., code: _Optional[str] = ..., second_factor_code: _Optional[str] = ...) -> None: ...

class TwoFactorConfigRequest(_message.Message):
    __slots__ = ("session_id", "user_id", "enabled", "method", "totp_confirmation_code")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    TOTP_CONFIRMATION_CODE_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    user_id: str
    enabled: bool
    method: str
    totp_confirmation_code: str
    def __init__(self, session_id: _Optional[str] = ..., user_id: _Optional[str] = ..., enabled: _Optional[bool] = ..., method: _Optional[str] = ..., totp_confirmation_code: _Optional[str] = ...) -> None: ...

class TwoFactorConfigResponse(_message.Message):
    __slots__ = ("enabled", "method", "totp_secret", "provisioning_uri", "error_code", "error_detail")
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    TOTP_SECRET_FIELD_NUMBER: _ClassVar[int]
    PROVISIONING_URI_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    method: str
    totp_secret: str
    provisioning_uri: str
    error_code: str
    error_detail: str
    def __init__(self, enabled: _Optional[bool] = ..., method: _Optional[str] = ..., totp_secret: _Optional[str] = ..., provisioning_uri: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class StepUpRequest(_message.Message):
    __slots__ = ("session_id", "method", "action")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    method: str
    action: str
    def __init__(self, session_id: _Optional[str] = ..., method: _Optional[str] = ..., action: _Optional[str] = ...) -> None: ...

class StepUpChallengeResponse(_message.Message):
    __slots__ = ("challenge_id", "method", "parameters_json", "error_code", "error_detail")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    method: str
    parameters_json: str
    error_code: str
    error_detail: str
    def __init__(self, challenge_id: _Optional[str] = ..., method: _Optional[str] = ..., parameters_json: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class StepUpCompleteRequest(_message.Message):
    __slots__ = ("session_id", "challenge_id", "response")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    challenge_id: str
    response: str
    def __init__(self, session_id: _Optional[str] = ..., challenge_id: _Optional[str] = ..., response: _Optional[str] = ...) -> None: ...

class StepUpCompleteResponse(_message.Message):
    __slots__ = ("satisfied", "satisfied_at_unix", "error_code", "error_detail")
    SATISFIED_FIELD_NUMBER: _ClassVar[int]
    SATISFIED_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    satisfied: bool
    satisfied_at_unix: int
    error_code: str
    error_detail: str
    def __init__(self, satisfied: _Optional[bool] = ..., satisfied_at_unix: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ValidateSessionRequest(_message.Message):
    __slots__ = ("session_id", "http_method", "csrf_token")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    HTTP_METHOD_FIELD_NUMBER: _ClassVar[int]
    CSRF_TOKEN_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    http_method: str
    csrf_token: str
    def __init__(self, session_id: _Optional[str] = ..., http_method: _Optional[str] = ..., csrf_token: _Optional[str] = ...) -> None: ...

class RevokeSessionRequest(_message.Message):
    __slots__ = ("session_id", "all_for_user", "user_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    ALL_FOR_USER_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    all_for_user: bool
    user_id: str
    def __init__(self, session_id: _Optional[str] = ..., all_for_user: _Optional[bool] = ..., user_id: _Optional[str] = ...) -> None: ...

class RevokeResponse(_message.Message):
    __slots__ = ("revoked", "sessions_revoked", "error_code", "error_detail")
    REVOKED_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_REVOKED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    revoked: bool
    sessions_revoked: int
    error_code: str
    error_detail: str
    def __init__(self, revoked: _Optional[bool] = ..., sessions_revoked: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class BreakGlassRequest(_message.Message):
    __slots__ = ("staff_user_id", "target_client_user_id", "reason", "duration_minutes")
    STAFF_USER_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_CLIENT_USER_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    DURATION_MINUTES_FIELD_NUMBER: _ClassVar[int]
    staff_user_id: str
    target_client_user_id: str
    reason: str
    duration_minutes: int
    def __init__(self, staff_user_id: _Optional[str] = ..., target_client_user_id: _Optional[str] = ..., reason: _Optional[str] = ..., duration_minutes: _Optional[int] = ...) -> None: ...

class BreakGlassResponse(_message.Message):
    __slots__ = ("grant_id", "granted_at_unix", "expires_at_unix", "error_code", "error_detail")
    GRANT_ID_FIELD_NUMBER: _ClassVar[int]
    GRANTED_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    grant_id: str
    granted_at_unix: int
    expires_at_unix: int
    error_code: str
    error_detail: str
    def __init__(self, grant_id: _Optional[str] = ..., granted_at_unix: _Optional[int] = ..., expires_at_unix: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class BreakGlassCheckRequest(_message.Message):
    __slots__ = ("staff_user_id", "target_client_user_id")
    STAFF_USER_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_CLIENT_USER_ID_FIELD_NUMBER: _ClassVar[int]
    staff_user_id: str
    target_client_user_id: str
    def __init__(self, staff_user_id: _Optional[str] = ..., target_client_user_id: _Optional[str] = ...) -> None: ...

class BreakGlassCheckResponse(_message.Message):
    __slots__ = ("allowed", "error_code", "error_detail")
    ALLOWED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    allowed: bool
    error_code: str
    error_detail: str
    def __init__(self, allowed: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListAuthMethodsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AuthMethodStatus(_message.Message):
    __slots__ = ("method", "enabled", "available", "detail")
    METHOD_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    method: str
    enabled: bool
    available: bool
    detail: str
    def __init__(self, method: _Optional[str] = ..., enabled: _Optional[bool] = ..., available: _Optional[bool] = ..., detail: _Optional[str] = ...) -> None: ...

class ListAuthMethodsResponse(_message.Message):
    __slots__ = ("methods", "tenancy_mode", "two_factor_policy", "error_code", "error_detail")
    METHODS_FIELD_NUMBER: _ClassVar[int]
    TENANCY_MODE_FIELD_NUMBER: _ClassVar[int]
    TWO_FACTOR_POLICY_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    methods: _containers.RepeatedCompositeFieldContainer[AuthMethodStatus]
    tenancy_mode: str
    two_factor_policy: str
    error_code: str
    error_detail: str
    def __init__(self, methods: _Optional[_Iterable[_Union[AuthMethodStatus, _Mapping]]] = ..., tenancy_mode: _Optional[str] = ..., two_factor_policy: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
