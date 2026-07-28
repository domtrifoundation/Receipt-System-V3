from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GroupEntry(_message.Message):
    __slots__ = ("group_id", "name", "created_by", "created_at")
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    group_id: str
    name: str
    created_by: str
    created_at: str
    def __init__(self, group_id: _Optional[str] = ..., name: _Optional[str] = ..., created_by: _Optional[str] = ..., created_at: _Optional[str] = ...) -> None: ...

class MembershipEntry(_message.Message):
    __slots__ = ("group_id", "user_id", "is_group_manager", "joined_at", "added_by")
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    IS_GROUP_MANAGER_FIELD_NUMBER: _ClassVar[int]
    JOINED_AT_FIELD_NUMBER: _ClassVar[int]
    ADDED_BY_FIELD_NUMBER: _ClassVar[int]
    group_id: str
    user_id: str
    is_group_manager: bool
    joined_at: str
    added_by: str
    def __init__(self, group_id: _Optional[str] = ..., user_id: _Optional[str] = ..., is_group_manager: _Optional[bool] = ..., joined_at: _Optional[str] = ..., added_by: _Optional[str] = ...) -> None: ...

class CreateGroupRequest(_message.Message):
    __slots__ = ("session_id", "name")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    name: str
    def __init__(self, session_id: _Optional[str] = ..., name: _Optional[str] = ...) -> None: ...

class GroupResponse(_message.Message):
    __slots__ = ("group", "error_code", "error_detail")
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    group: GroupEntry
    error_code: str
    error_detail: str
    def __init__(self, group: _Optional[_Union[GroupEntry, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class AddMemberRequest(_message.Message):
    __slots__ = ("session_id", "group_id", "user_id", "is_group_manager")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    IS_GROUP_MANAGER_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    group_id: str
    user_id: str
    is_group_manager: bool
    def __init__(self, session_id: _Optional[str] = ..., group_id: _Optional[str] = ..., user_id: _Optional[str] = ..., is_group_manager: _Optional[bool] = ...) -> None: ...

class MembershipResponse(_message.Message):
    __slots__ = ("membership", "error_code", "error_detail")
    MEMBERSHIP_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    membership: MembershipEntry
    error_code: str
    error_detail: str
    def __init__(self, membership: _Optional[_Union[MembershipEntry, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class RemoveMemberRequest(_message.Message):
    __slots__ = ("session_id", "group_id", "user_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    group_id: str
    user_id: str
    def __init__(self, session_id: _Optional[str] = ..., group_id: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class RemoveMemberResponse(_message.Message):
    __slots__ = ("removed", "error_code", "error_detail")
    REMOVED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    removed: bool
    error_code: str
    error_detail: str
    def __init__(self, removed: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class SetManagerRequest(_message.Message):
    __slots__ = ("session_id", "group_id", "user_id", "is_group_manager", "reason")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    IS_GROUP_MANAGER_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    group_id: str
    user_id: str
    is_group_manager: bool
    reason: str
    def __init__(self, session_id: _Optional[str] = ..., group_id: _Optional[str] = ..., user_id: _Optional[str] = ..., is_group_manager: _Optional[bool] = ..., reason: _Optional[str] = ...) -> None: ...

class EffectiveGroupRequest(_message.Message):
    __slots__ = ("session_id", "user_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    user_id: str
    def __init__(self, session_id: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class EffectiveGroupResponse(_message.Message):
    __slots__ = ("has_group", "group_id", "error_code", "error_detail")
    HAS_GROUP_FIELD_NUMBER: _ClassVar[int]
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    has_group: bool
    group_id: str
    error_code: str
    error_detail: str
    def __init__(self, has_group: _Optional[bool] = ..., group_id: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListMembersRequest(_message.Message):
    __slots__ = ("session_id", "group_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    group_id: str
    def __init__(self, session_id: _Optional[str] = ..., group_id: _Optional[str] = ...) -> None: ...

class ListMembersResponse(_message.Message):
    __slots__ = ("members", "error_code", "error_detail")
    MEMBERS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    members: _containers.RepeatedCompositeFieldContainer[MembershipEntry]
    error_code: str
    error_detail: str
    def __init__(self, members: _Optional[_Iterable[_Union[MembershipEntry, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
