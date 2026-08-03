from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TicketInfo(_message.Message):
    __slots__ = ("ticket_id", "created_by", "subject", "status", "assigned_to", "related_receipt_id", "created_at", "updated_at")
    TICKET_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_TO_FIELD_NUMBER: _ClassVar[int]
    RELATED_RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    ticket_id: str
    created_by: str
    subject: str
    status: str
    assigned_to: str
    related_receipt_id: str
    created_at: str
    updated_at: str
    def __init__(self, ticket_id: _Optional[str] = ..., created_by: _Optional[str] = ..., subject: _Optional[str] = ..., status: _Optional[str] = ..., assigned_to: _Optional[str] = ..., related_receipt_id: _Optional[str] = ..., created_at: _Optional[str] = ..., updated_at: _Optional[str] = ...) -> None: ...

class TicketMessageInfo(_message.Message):
    __slots__ = ("ticket_id", "author", "body", "posted_at")
    TICKET_ID_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    POSTED_AT_FIELD_NUMBER: _ClassVar[int]
    ticket_id: str
    author: str
    body: str
    posted_at: str
    def __init__(self, ticket_id: _Optional[str] = ..., author: _Optional[str] = ..., body: _Optional[str] = ..., posted_at: _Optional[str] = ...) -> None: ...

class CreateTicketRequest(_message.Message):
    __slots__ = ("session_id", "subject", "body", "related_receipt_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    RELATED_RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    subject: str
    body: str
    related_receipt_id: str
    def __init__(self, session_id: _Optional[str] = ..., subject: _Optional[str] = ..., body: _Optional[str] = ..., related_receipt_id: _Optional[str] = ...) -> None: ...

class PostMessageRequest(_message.Message):
    __slots__ = ("session_id", "ticket_id", "body")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TICKET_ID_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    ticket_id: str
    body: str
    def __init__(self, session_id: _Optional[str] = ..., ticket_id: _Optional[str] = ..., body: _Optional[str] = ...) -> None: ...

class GetTicketMessagesRequest(_message.Message):
    __slots__ = ("session_id", "ticket_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TICKET_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    ticket_id: str
    def __init__(self, session_id: _Optional[str] = ..., ticket_id: _Optional[str] = ...) -> None: ...

class ListMessagesResponse(_message.Message):
    __slots__ = ("messages", "error_code", "error_detail")
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    messages: _containers.RepeatedCompositeFieldContainer[TicketMessageInfo]
    error_code: str
    error_detail: str
    def __init__(self, messages: _Optional[_Iterable[_Union[TicketMessageInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class UpdateStatusRequest(_message.Message):
    __slots__ = ("session_id", "ticket_id", "target_status")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TICKET_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_STATUS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    ticket_id: str
    target_status: str
    def __init__(self, session_id: _Optional[str] = ..., ticket_id: _Optional[str] = ..., target_status: _Optional[str] = ...) -> None: ...

class AssignRequest(_message.Message):
    __slots__ = ("session_id", "ticket_id", "assignee_user_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TICKET_ID_FIELD_NUMBER: _ClassVar[int]
    ASSIGNEE_USER_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    ticket_id: str
    assignee_user_id: str
    def __init__(self, session_id: _Optional[str] = ..., ticket_id: _Optional[str] = ..., assignee_user_id: _Optional[str] = ...) -> None: ...

class ListTicketsRequest(_message.Message):
    __slots__ = ("session_id", "statuses", "created_by", "assigned_to", "unassigned_only", "related_receipt_id", "limit")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    STATUSES_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_TO_FIELD_NUMBER: _ClassVar[int]
    UNASSIGNED_ONLY_FIELD_NUMBER: _ClassVar[int]
    RELATED_RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    statuses: _containers.RepeatedScalarFieldContainer[str]
    created_by: str
    assigned_to: str
    unassigned_only: bool
    related_receipt_id: str
    limit: int
    def __init__(self, session_id: _Optional[str] = ..., statuses: _Optional[_Iterable[str]] = ..., created_by: _Optional[str] = ..., assigned_to: _Optional[str] = ..., unassigned_only: _Optional[bool] = ..., related_receipt_id: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class TicketResponse(_message.Message):
    __slots__ = ("ticket", "error_code", "error_detail")
    TICKET_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    ticket: TicketInfo
    error_code: str
    error_detail: str
    def __init__(self, ticket: _Optional[_Union[TicketInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class TicketMessageResponse(_message.Message):
    __slots__ = ("message", "error_code", "error_detail")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    message: TicketMessageInfo
    error_code: str
    error_detail: str
    def __init__(self, message: _Optional[_Union[TicketMessageInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListTicketsResponse(_message.Message):
    __slots__ = ("tickets", "error_code", "error_detail")
    TICKETS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    tickets: _containers.RepeatedCompositeFieldContainer[TicketInfo]
    error_code: str
    error_detail: str
    def __init__(self, tickets: _Optional[_Iterable[_Union[TicketInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
