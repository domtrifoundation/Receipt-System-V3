# V3 Deep Dive: Groups (sub-API)

**Parent:** Data model and membership live in Auth & Tenancy's own top-level database (`v3-deepdive-05-auth-tenancy-api.md` §5.2's placement reasoning), but the feature itself is genuinely cross-cutting — Persistence, Search/Query, and Export Framework all have real, load-bearing pieces of it. Extracted into its own document per `docs/PRINCIPLES.md` §1.8's threshold (own data model, cross-referenced from four APIs, its own gRPC surface) after being wrongly buried as a subsection of Auth's own deep-dive.

**Companion files:** `v3-deepdive-21-search-query-api.md` §4 (the group-scoped query path), `v3-deepdive-31-export-framework.md` §7 (`group_export.py`), `v3-deepdive-13-persistence-api.md` §1 (the `group_id` receipt tag), `v3-deepdive-10-execution-core-api.md` §6 (the ingestion-time tagging hook).

**Status:** New dedicated document, corrected out of Auth's own deep-dive. Genuinely new feature, no V2 lineage — surfaced during the Setup Sequence walkthrough while resolving whether self-hosted installs use the tier system at all.

---

## 1. Scope & boundary

Groups owns letting an owner (or a designated group manager) organize users into teams whose receipts get automatically pooled for aggregate, labeled reporting — the real case this solves: a company self-hosting for its whole team, where employees each upload their own receipts but management wants one combined view across the team, labeled by who contributed what. It does not:
- **own the actual data being aggregated** — receipts stay in each member's own Persistence database exactly as isolated as they'd otherwise be; Groups only adds a visibility grant and a tagging convention, never a shared data store.
- **replace break-glass** — see §2, a deliberately distinct third access shape, never modeled as "break-glass that never expires."
- **own the export mechanism itself** — `group_export.py` (§6) is Export Framework's own provider, reusing its existing `excel_general.py`-style technique; Groups only supplies the access rule and the data to pull.

---

## 2. A third access-control shape, distinct from both plain isolation and break-glass — the core design decision
This project already has two access-control shapes: **plain per-user isolation** (structural, nobody sees anyone else's data by default) and **break-glass** (temporary, logged, reason-required, for staff emergency access). Group visibility is a genuinely different, third shape: **persistent, structural, and consented-to by the nature of joining the group** — an employee uploading receipts for their employer's group expects their manager to see them, the same way a real expense-reporting system works; it's not an emergency exception, it's the expected, ongoing arrangement. Worth keeping these three shapes conceptually distinct rather than trying to model Group visibility as "break-glass that never expires" (a real temptation, and a real mistake — the two have different audit expectations, different UX, and different failure modes if conflated).

---

## 3. Package layout

```
core/groups/
  __init__.py
  contracts.py             # Group, GroupMembership, error types
  membership.py                # create/add/remove/manager-toggle
  effective_group.py             # get_effective_group() — the ingestion-time hook, see §5
  permission_gate.py               # is_group_manager checks, consumed by Search/Query
  errors.py
```
Lives operationally inside Auth & Tenancy's own database (its deep-dive §5.2) — this is identity/org-structure data, squarely the same category as users/sessions/break-glass grants, not a reason to invent a fourth top-level database. The package is separate from Auth's own `core/auth/` package because the feature's real surface area (§1) extends well past what Auth alone owns.

---

## 4. Data contracts

```python
@dataclass(frozen=True)
class Group:
    group_id: str
    name: str
    created_by: str            # the owner or staff member who created it
    created_at: datetime

@dataclass(frozen=True)
class GroupMembership:
    group_id: str
    user_id: str
    is_group_manager: bool      # see §4.1 — a per-membership flag, not a system-wide role
    joined_at: datetime
    added_by: str                 # actor who added this member — real audit value, who granted this ongoing visibility relationship
```

### 4.1 Who can see a group's aggregate data
Instance owner and staff can already see across the whole instance via their existing system-wide privileges (break-glass for staff, unconditional for owner) — Groups don't need to grant them anything new. **The genuinely new capability is `is_group_manager`**: a specific member of a group, flagged as that group's own manager, gets aggregate visibility across *their own group's* members only — not the whole instance, not other groups. This is the concrete "team lead sees their team's receipts, not the whole company's other teams" pattern a real self-hosted company deployment would actually want, and it's a meaningfully narrower grant than making someone system-wide staff just to let them see their own team's data.

---

## 5. How receipt tagging actually happens — updated for multi-group membership
```python
async def get_effective_group(user_id: str) -> str | None:
    """Called by Execution Core at ingestion time (its own deep-dive §6's
    checkpointing sequence is the natural hook — same 'one chokepoint,
    not scattered calls' principle already applied to Historian's
    narrative track, v3-deepdive-29-historian.md §5) — returns the
    user's own explicitly-set 'active group' (§11's own resolution of
    the multi-group membership question: a simple selector, defaulting
    to whichever group the user most recently used, not an ambiguous
    auto-pick among several memberships), or None if they're in no
    group at all. A receipt uploaded by a group member gets group_id
    stamped onto it as part of the normal write path, not a separate
    tagging step someone could forget to run."""
```
The `group_id` column itself lives on the receipt row in Persistence's own database (its deep-dive §1) — Groups supplies the value via this hook, Persistence just stores it faithfully, consistent with the project's own "who decides vs. who stores" boundary discipline applied everywhere else.

---

## 6. The group export
`group_export.py` (Export Framework's own package, `v3-deepdive-31-export-framework.md` §7) — pulls every receipt tagged with a given `group_id`, with an added column identifying the contributing user (by name or email, not raw `user_id`), reusing the same `excel_general.py`-style formula-driven summary sheet technique rather than inventing a new export format from scratch. Access-gated by §4.1's rule: only callable by the instance owner/staff or that specific group's own `is_group_manager` members — that provider calls this sub-API's own permission check before generating anything, never trusts a bare `group_id` parameter on its own.

---

## 7. The group-scoped query path
Search/Query's own permission gate (its deep-dive §4) has a dedicated `search_group()` function alongside its single-target `search()` — gated the same way (staff/owner privileges, or `is_group_manager` for that specific group), checked live at query time against this sub-API's own current membership state, never cached or assumed stable across a session. Persistent and structural doesn't mean "never re-checked," it means "no expiry timer" — a real distinction worth preserving in the enforcement code, not just the prose describing it.

---

## 8. Asyncio
Thin CRUD over Auth's own database plus the one real hook (`get_effective_group`, called once per ingestion) — I/O-bound, no compute-bound work of its own, the same shape as every other thin-orchestration sub-API in this batch. **Forward-compatibility check, explicit rather than assumed**: no new dependency of any kind is introduced by this sub-API — it's pure CRUD over Auth's own already-established SQLite/async-wrapper stack — and no compute-bound pure-Python work exists anywhere in scope for free-threading to meaningfully help with.

---

## 9. gRPC surface

```protobuf
service GroupsService {
  rpc CreateGroup(CreateGroupRequest) returns (GroupResponse);
  rpc AddGroupMember(AddMemberRequest) returns (GroupMembershipResponse);
  rpc RemoveGroupMember(RemoveMemberRequest) returns (RemoveMemberResponse);
  rpc SetGroupManager(SetManagerRequest) returns (GroupMembershipResponse);         // toggles is_group_manager
  rpc GetEffectiveGroup(EffectiveGroupRequest) returns (EffectiveGroupResponse);      // §5's ingestion-time hook
  rpc ListGroupMembers(ListMembersRequest) returns (ListMembersResponse);             // gated by §4.1's rule
}
```

---

## 10. Testing hooks
- **Isolation-by-default test**: confirms a user with no group membership sees zero behavioral change — Groups is additive, never a regression on plain per-user isolation for anyone not opted into one.
- **`is_group_manager` scope test**: confirms a group manager's aggregate visibility stops exactly at their own group's membership list, never leaking into another group's data.
- **Live re-check test**: confirms a `search_group()` call made immediately after a membership removal correctly loses access — the concrete validation of §7's "no expiry timer doesn't mean no re-check" claim.

---

## 11. Open questions for this deep-dive (logged, not guessed at)
- **Multi-group membership, resolved: yes, a user can belong to more than one group.** More flexible and closer to real org structures than a single-group restriction. A new receipt tags to the user's own explicitly-set "active group" — a simple selector defaulting to whichever group they most recently used — rather than an ambiguous auto-selection when multiple memberships exist.
- **Group-manager assignment UX, resolved: owner/staff only, and yes, it gets its own Audit entry.** Flipping `is_group_manager` is a real access-elevation action — consistent with every other privileged action in this project being Audit-logged, the same reasoning Supervisor's own `ForceWake`/`PinServiceVersion` questions just resolved the same way.
- (Webapp/TUI surfaces for group management — resolved, no longer open. Webapp: `v3-deepdive-44-webapp.md` §5.4. TUI: `v3-deepdive-14-interface-api.md` §3.2.1, added deliberately to that document's own enumerated custom-screen exception list with the explicit justification that list's own rule requires — group membership is a two-level relational structure the flat `MenuItemSpec` pattern genuinely can't express, the same structural reason the vendor editor earned its own exception.)
