"""Real group management (`settings.py`'s sibling root-menu entry, `groups`) — create/
rename groups, add/remove members, toggle `is_group_manager`, per `v3-deepdive-41-
groups.md` §3.2.1's own justification for this being a custom screen (a two-level
relational structure — a group, then its members, each with an independent manager
flag — the flat `MenuItemSpec` pattern genuinely cannot express).

**A real, previously-undiscovered bug in Groups' own deployment was found and fixed
while building this screen's own backend call path**: `core/groups/service.py`'s
`__main__` never constructed a real `SessionResolver`, so `PermissionGate` silently
defaulted to `DenyAllSessions()` — the real running Groups service denied every gated
call it ever received. `core/groups/auth_client.py`'s `GrpcSessionResolver` is the fix.

**Session resolution here is the honest single-tenant path, not a full login flow.**
This screen calls Auth's `ValidateSession("")` to get a real session — in single-tenant
mode this returns the real implicit-owner session (`docs/apis/v3-deepdive-05-auth-
tenancy-api.md` §6.2); in multi-tenant mode with no session already established, Auth
correctly refuses, and this screen reports that plainly rather than pretending a session
exists. A full multi-provider login screen is real, separate, larger follow-up work.

**No `ListGroups` RPC exists** (`groups.proto`'s own real, closed RPC set) — an operator
manages a group by its own `group_id`, remembered from `CreateGroup`'s own response;
there is no way to enumerate every group from a cold start yet.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, ListItem, ListView, Static


class GroupsScreen(Screen):
    """A real, live-found UI bug: this screen has enough stacked controls to overflow a
    short terminal (confirmed live at the default 80x24 test size — the bottom button
    rendered off-screen, and a click computed for its position landed on the Footer's
    own binding hint instead, silently triggering "Back"). `VerticalScroll` (not a plain
    `Vertical`) is the fix, matching `CreditsScreen`'s own established pattern for
    content that can exceed one screen's height."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, *, auth_address_override: str | None = None, groups_address_override: str | None = None) -> None:
        super().__init__()
        self._auth_address_override = auth_address_override
        self._groups_address_override = groups_address_override
        self._session_id: str | None = None
        self._current_group_id: str = ""

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Static("Groups", id="groups-title"),
            Input(placeholder="New group name", id="groups-new-name"),
            Button("Create Group", id="groups-create"),
            Input(placeholder="Group ID to manage", id="groups-group-id"),
            Button("Load Members", id="groups-load"),
            ListView(id="groups-members"),
            Input(placeholder="Member user_id", id="groups-member-id"),
            Button("Add Member", id="groups-add-member"),
            Button("Remove Member", id="groups-remove-member"),
            Button("Toggle Manager", id="groups-toggle-manager"),
            Static("", id="groups-status"),
            id="groups-container",
        )
        yield Footer()

    def _auth_address(self) -> str:
        if self._auth_address_override is not None:
            return self._auth_address_override
        from common.blob_client import resolve_service_address
        from common.install_paths import resolve_install_root
        from pathlib import Path

        install_root = resolve_install_root(Path(__file__))
        if install_root is None:
            return "127.0.0.1:50056"
        return resolve_service_address(install_root, "auth", "127.0.0.1:50056")

    def _groups_address(self) -> str:
        if self._groups_address_override is not None:
            return self._groups_address_override
        from common.blob_client import resolve_service_address
        from common.install_paths import resolve_install_root
        from pathlib import Path

        install_root = resolve_install_root(Path(__file__))
        if install_root is None:
            return "127.0.0.1:50067"
        return resolve_service_address(install_root, "groups", "127.0.0.1:50067")

    async def on_mount(self) -> None:
        await self._ensure_session()

    async def _ensure_session(self) -> bool:
        if self._session_id is not None:
            return True
        import grpc

        from core.auth.generated import auth_pb2 as pb
        from core.auth.generated import auth_pb2_grpc as pb_grpc

        status = self.query_one("#groups-status", Static)
        try:
            async with grpc.aio.insecure_channel(self._auth_address()) as channel:
                response = await pb_grpc.AuthServiceStub(channel).ValidateSession(pb.ValidateSessionRequest(session_id=""))
            self._session_id = response.session_id
            return True
        except grpc.aio.AioRpcError as exc:
            status.update(f"No session available — sign in required ({exc.details()}).")
            return False

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        status = self.query_one("#groups-status", Static)
        if not await self._ensure_session():
            return

        if event.button.id == "groups-create":
            await self._create_group()
        elif event.button.id == "groups-load":
            await self._load_members()
        elif event.button.id == "groups-add-member":
            await self._add_member()
        elif event.button.id == "groups-remove-member":
            await self._remove_member()
        elif event.button.id == "groups-toggle-manager":
            await self._toggle_manager()

    async def _create_group(self) -> None:
        import grpc

        from core.groups.generated import groups_pb2 as pb
        from core.groups.generated import groups_pb2_grpc as pb_grpc

        name = self.query_one("#groups-new-name", Input).value.strip()
        status = self.query_one("#groups-status", Static)
        if not name:
            status.update("Enter a group name first.")
            return
        async with grpc.aio.insecure_channel(self._groups_address()) as channel:
            response = await pb_grpc.GroupsServiceStub(channel).CreateGroup(
                pb.CreateGroupRequest(session_id=self._session_id, name=name)
            )
        if response.error_code:
            status.update(f"Create failed: {response.error_code} — {response.error_detail}")
            return
        self._current_group_id = response.group.group_id
        self.query_one("#groups-group-id", Input).value = response.group.group_id
        status.update(f"Created group {response.group.group_id} ({response.group.name}).")

    async def _load_members(self) -> None:
        import grpc

        from core.groups.generated import groups_pb2 as pb
        from core.groups.generated import groups_pb2_grpc as pb_grpc

        group_id = self.query_one("#groups-group-id", Input).value.strip()
        status = self.query_one("#groups-status", Static)
        members_list = self.query_one("#groups-members", ListView)
        if not group_id:
            status.update("Enter a group ID first.")
            return
        self._current_group_id = group_id
        async with grpc.aio.insecure_channel(self._groups_address()) as channel:
            response = await pb_grpc.GroupsServiceStub(channel).ListGroupMembers(
                pb.ListMembersRequest(session_id=self._session_id, group_id=group_id)
            )
        if response.error_code:
            status.update(f"Load failed: {response.error_code} — {response.error_detail}")
            return
        await members_list.clear()
        for m in response.members:
            manager_tag = " (manager)" if m.is_group_manager else ""
            await members_list.append(ListItem(Static(f"{m.user_id}{manager_tag}"), id=f"member-{m.user_id}"))
        status.update(f"{len(response.members)} member(s).")

    async def _add_member(self) -> None:
        import grpc

        from core.groups.generated import groups_pb2 as pb
        from core.groups.generated import groups_pb2_grpc as pb_grpc

        user_id = self.query_one("#groups-member-id", Input).value.strip()
        status = self.query_one("#groups-status", Static)
        if not self._current_group_id or not user_id:
            status.update("Load a group and enter a member user_id first.")
            return
        async with grpc.aio.insecure_channel(self._groups_address()) as channel:
            response = await pb_grpc.GroupsServiceStub(channel).AddGroupMember(
                pb.AddMemberRequest(session_id=self._session_id, group_id=self._current_group_id, user_id=user_id)
            )
        status.update("Member added." if not response.error_code else f"Add failed: {response.error_code} — {response.error_detail}")
        await self._load_members()

    async def _remove_member(self) -> None:
        import grpc

        from core.groups.generated import groups_pb2 as pb
        from core.groups.generated import groups_pb2_grpc as pb_grpc

        user_id = self.query_one("#groups-member-id", Input).value.strip()
        status = self.query_one("#groups-status", Static)
        if not self._current_group_id or not user_id:
            status.update("Load a group and enter a member user_id first.")
            return
        async with grpc.aio.insecure_channel(self._groups_address()) as channel:
            response = await pb_grpc.GroupsServiceStub(channel).RemoveGroupMember(
                pb.RemoveMemberRequest(session_id=self._session_id, group_id=self._current_group_id, user_id=user_id)
            )
        status.update("Member removed." if response.removed else f"Remove failed: {response.error_code} — {response.error_detail}")
        await self._load_members()

    async def _toggle_manager(self) -> None:
        import grpc

        from core.groups.generated import groups_pb2 as pb
        from core.groups.generated import groups_pb2_grpc as pb_grpc

        user_id = self.query_one("#groups-member-id", Input).value.strip()
        status = self.query_one("#groups-status", Static)
        if not self._current_group_id or not user_id:
            status.update("Load a group and enter a member user_id first.")
            return
        # A real toggle needs the member's own current state -- re-fetched here rather
        # than trusting stale UI state, since another session could have changed it since
        # this screen last loaded members.
        async with grpc.aio.insecure_channel(self._groups_address()) as channel:
            stub = pb_grpc.GroupsServiceStub(channel)
            current = await stub.ListGroupMembers(pb.ListMembersRequest(session_id=self._session_id, group_id=self._current_group_id))
            existing = next((m for m in current.members if m.user_id == user_id), None)
            new_value = not (existing.is_group_manager if existing else False)
            response = await stub.SetGroupManager(pb.SetManagerRequest(
                session_id=self._session_id, group_id=self._current_group_id, user_id=user_id,
                is_group_manager=new_value, reason="toggled via TUI",
            ))
        status.update(f"Manager set to {new_value}." if not response.error_code else f"Toggle failed: {response.error_code} — {response.error_detail}")
        await self._load_members()


__all__ = ["GroupsScreen"]
