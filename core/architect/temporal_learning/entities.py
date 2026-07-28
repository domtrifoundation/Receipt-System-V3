"""Corporation/Branch/Franchiser storage and CRUD (`v3-deepdive-40-temporal-learning.md` §4).

Two rules make this file what it is.

**Franchisers are referenced, never embedded.** `Branch.franchiser_id` is a link. One
franchiser operating a branch of one corporation and a branch of another is a real,
common PH arrangement, and both branches point at the same `Franchiser` record — so a TIN
correction is applied once and is immediately true everywhere. `resolve_branch` exists to
make that the easy path: callers get the branch, its corporation and its franchiser
resolved at read time rather than being tempted to denormalize.

**Direct writes here are `LOCAL` only.** Creating or editing anything in `GLOBAL` goes
through `moderation_queue.py`; this module's only route into that layer is
`apply_contribution`, which the queue calls after its own gates have passed. That is what
keeps "nothing reaches global without review" a structural property rather than a rule
every caller has to remember.

**On storage**: `EntityStore` is a Protocol with an in-memory implementation here.
Persistence owns disk in this system, and Architect is being implemented before
Persistence's write path exists — so rather than opening a second file handle onto a
database and having to unpick it later, this keeps the seam explicit and lets the
Persistence-backed store drop in behind the same Protocol.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Protocol

from .contracts import (
    Branch,
    Corporation,
    Entity,
    EntityResult,
    EntityType,
    Franchiser,
    LearningError,
    ListEntitiesResult,
    VendorLayer,
)
from .errors import LearningErrorCode, learning_message_for

#: Which contract class implements each entity type, and which field is its id. Kept in
#: one place so a new caller cannot get the pairing subtly wrong.
_ENTITY_CLASSES: dict[str, type] = {
    "corporation": Corporation,
    "branch": Branch,
    "franchiser": Franchiser,
}
_ID_FIELDS: dict[str, str] = {
    "corporation": "corporation_id",
    "branch": "branch_id",
    "franchiser": "franchiser_id",
}
#: Fields a caller must supply per type. Everything else has a contract default.
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "corporation": ("name", "corporate_tin"),
    "branch": ("corporation_id", "address"),
    "franchiser": ("name", "franchiser_tin"),
}


def _error(code: str, detail: str = "") -> LearningError:
    return LearningError(code=code, detail=detail or learning_message_for(code))


def entity_type_of(entity: Entity) -> EntityType:
    if isinstance(entity, Corporation):
        return "corporation"
    if isinstance(entity, Branch):
        return "branch"
    return "franchiser"


def entity_id_of(entity: Entity) -> str:
    return getattr(entity, _ID_FIELDS[entity_type_of(entity)])


class EntityStore(Protocol):
    """The storage seam. Swapped for a Persistence-backed implementation when that exists."""

    def put(self, entity: Entity) -> None: ...

    def get(self, entity_type: EntityType, entity_id: str) -> Entity | None: ...

    def all_of(self, entity_type: EntityType) -> tuple[Entity, ...]: ...


class InMemoryEntityStore:
    """Process-local store. Plain dicts: a genuinely mutable registry, per §2.1.1."""

    def __init__(self) -> None:
        self._tables: dict[str, dict[str, Entity]] = {t: {} for t in _ENTITY_CLASSES}

    def put(self, entity: Entity) -> None:
        self._tables[entity_type_of(entity)][entity_id_of(entity)] = entity

    def get(self, entity_type: EntityType, entity_id: str) -> Entity | None:
        return self._tables[entity_type].get(entity_id)

    def all_of(self, entity_type: EntityType) -> tuple[Entity, ...]:
        return tuple(self._tables[entity_type].values())


class EntityManager:
    """CRUD over the three entities, with the layer rules enforced in one place."""

    def __init__(self, store: EntityStore | None = None) -> None:
        self._store: EntityStore = store if store is not None else InMemoryEntityStore()

    @property
    def store(self) -> EntityStore:
        return self._store

    # --------------------------------------------------------------- local writes

    def create(
        self,
        entity_type: EntityType,
        fields: Mapping[str, object],
        actor_user_id: str,
    ) -> EntityResult:
        """Create a `LOCAL`, unshared entity. No review of any kind (§3).

        This is the path an automated pipeline may take unattended: a private fact cannot
        hurt anyone but the user who created it, which is exactly what makes it safe to
        self-apply. Nothing here can produce a `GLOBAL` entity, whatever the caller passes.
        """
        problem = self._validate(entity_type, fields, for_create=True)
        if problem is not None:
            return EntityResult(error=problem)
        cls = _ENTITY_CLASSES[entity_type]
        payload = {k: v for k, v in fields.items() if k in _field_names(cls)}
        payload[_ID_FIELDS[entity_type]] = f"{entity_type[:4]}-{uuid.uuid4().hex[:12]}"
        payload["layer"] = VendorLayer.LOCAL
        payload["shared"] = False
        payload["owner_user_id"] = actor_user_id
        entity = cls(**payload)
        self._store.put(entity)
        return EntityResult(entity=entity)

    def update(
        self,
        entity_type: EntityType,
        entity_id: str,
        changes: Mapping[str, object],
        actor_user_id: str,
    ) -> EntityResult:
        """Edit a `LOCAL` entity in place.

        A `GLOBAL` entity is refused here and told why: correcting shared truth is a
        contribution, and letting it happen through the ordinary edit path would be a
        silent bypass of the whole review pipeline.
        """
        existing = self._store.get(entity_type, entity_id)
        if existing is None:
            return EntityResult(error=_error(LearningErrorCode.UNKNOWN_ENTITY, entity_id))
        if existing.layer is VendorLayer.GLOBAL:
            return EntityResult(
                error=_error(
                    LearningErrorCode.APPROVAL_REQUIRED,
                    "editing a global entity is a contribution, not a direct write",
                )
            )
        problem = self._validate(entity_type, changes, for_create=False)
        if problem is not None:
            return EntityResult(error=problem)
        allowed = _field_names(_ENTITY_CLASSES[entity_type]) - {
            _ID_FIELDS[entity_type], "layer", "shared", "owner_user_id", "created_at"
        }
        updated = replace(existing, **{k: v for k, v in changes.items() if k in allowed})
        self._store.put(updated)
        return EntityResult(entity=updated)

    def mark_shared(self, entity: Entity) -> Entity:
        """Record that an entity has been through the §3.1 share action.

        Called by `layering.share_entity`, never directly by a caller wanting to skip it —
        `shared` is a record of consent having been given, not a flag that grants it.
        """
        updated = replace(entity, shared=True)
        self._store.put(updated)
        return updated

    # ---------------------------------------------------------------- global write

    def apply_contribution(
        self,
        entity_type: EntityType,
        entity_id: str | None,
        change: Mapping[str, object],
    ) -> EntityResult:
        """Merge an approved contribution into the `GLOBAL` layer.

        Called only from the moderation queue's own merge step. A new entity is created in
        `GLOBAL`; a correction updates the target in place and promotes it. Kept here
        rather than in the queue so every write to an entity table goes through one module.
        """
        cls = _ENTITY_CLASSES[entity_type]
        # A `GLOBAL` entity may only reference other `GLOBAL` entities. Without this, a user
        # sharing a local branch lands a globally-visible branch still pointing at that
        # user's own `LOCAL` corporation — every other user sees a branch whose corporation
        # `list_visible` hides from them and `resolve_branch` returns `None` for. The
        # reference model §4 exists to protect is only worth anything if the thing on the
        # other end of the reference is actually resolvable by whoever can see the referrer.
        dangling = self._global_reference_problem(entity_type, change)
        if dangling is not None:
            return EntityResult(error=dangling)
        if entity_id is None:
            problem = self._validate(entity_type, change, for_create=True)
            if problem is not None:
                return EntityResult(error=problem)
            payload = {k: v for k, v in change.items() if k in _field_names(cls)}
            payload[_ID_FIELDS[entity_type]] = f"{entity_type[:4]}-{uuid.uuid4().hex[:12]}"
            payload["layer"] = VendorLayer.GLOBAL
            payload["shared"] = True
            entity = cls(**payload)
            self._store.put(entity)
            return EntityResult(entity=entity)

        existing = self._store.get(entity_type, entity_id)
        if existing is None:
            return EntityResult(error=_error(LearningErrorCode.UNKNOWN_ENTITY, entity_id))
        # `layer` and `shared` are excluded from what a change may carry and then set
        # explicitly below — a contribution proposing its own layer would be proposing to
        # skip the gate that approved it.
        # `owner_user_id` is excluded for the same reason `layer` and `shared` are: it is
        # placement, not a fact about the entity, and a contribution able to carry it could
        # reassign ownership of a global record as a side effect of a field correction.
        allowed = _field_names(cls) - {
            _ID_FIELDS[entity_type], "created_at", "layer", "shared", "owner_user_id"
        }
        updated = replace(
            existing,
            **{k: v for k, v in change.items() if k in allowed},
            layer=VendorLayer.GLOBAL,
            shared=True,
        )
        self._store.put(updated)
        return EntityResult(entity=updated)

    # ----------------------------------------------------------------------- reads

    def get(self, entity_type: EntityType, entity_id: str) -> EntityResult:
        found = self._store.get(entity_type, entity_id)
        if found is None:
            return EntityResult(error=_error(LearningErrorCode.UNKNOWN_ENTITY, entity_id))
        return EntityResult(entity=found)

    def list_visible(self, entity_type: EntityType, user_id: str | None) -> ListEntitiesResult:
        """Everything `GLOBAL`, plus this user's own `LOCAL` entries — never anyone else's.

        The visibility rule lives here and is applied on read, so a caller cannot see
        another user's local facts by asking a different question.
        """
        if entity_type not in _ENTITY_CLASSES:
            return ListEntitiesResult(
                error=_error(LearningErrorCode.UNKNOWN_ENTITY_TYPE, str(entity_type))
            )
        visible = tuple(
            e
            for e in self._store.all_of(entity_type)
            if e.layer is VendorLayer.GLOBAL
            or (user_id is not None and e.owner_user_id == user_id)
        )
        return ListEntitiesResult(entities=visible)

    def branches_for(self, corporation_id: str) -> tuple[Branch, ...]:
        return tuple(
            b
            for b in self._store.all_of("branch")
            if isinstance(b, Branch) and b.corporation_id == corporation_id
        )

    def branches_of_franchiser(self, franchiser_id: str) -> tuple[Branch, ...]:
        return tuple(
            b
            for b in self._store.all_of("branch")
            if isinstance(b, Branch) and b.franchiser_id == franchiser_id
        )

    def resolve_branch(
        self, branch_id: str
    ) -> tuple[Branch | None, Corporation | None, Franchiser | None]:
        """Resolve a branch's references at read time.

        The whole point of §4's split: a franchiser's current name and TIN are read from
        the one `Franchiser` record, so a correction to it is reflected by every branch
        immediately, with no per-branch fix-up and nothing to keep in agreement.
        """
        branch = self._store.get("branch", branch_id)
        if not isinstance(branch, Branch):
            return None, None, None
        corporation = self._store.get("corporation", branch.corporation_id)
        franchiser = (
            self._store.get("franchiser", branch.franchiser_id)
            if branch.franchiser_id is not None
            else None
        )
        return (
            branch,
            corporation if isinstance(corporation, Corporation) else None,
            franchiser if isinstance(franchiser, Franchiser) else None,
        )

    # ------------------------------------------------------------------ validation

    def _global_reference_problem(
        self, entity_type: EntityType, change: Mapping[str, object]
    ) -> LearningError | None:
        """Refuse a global write whose references do not resolve in the global layer.

        Only branches carry references, so only branches can produce this. A local
        corporation id riding along in a shared branch's proposed change is the concrete
        case: the branch is approved on its own merits, and nothing in the pipeline was
        otherwise checking that the corporation it names had been through the gate too.
        """
        if entity_type != "branch":
            return None
        for field_name, referenced_type in (
            ("corporation_id", "corporation"),
            ("franchiser_id", "franchiser"),
        ):
            referenced_id = change.get(field_name)
            if referenced_id is None:
                continue
            referenced = self._store.get(referenced_type, str(referenced_id))
            if referenced is None:
                return _error(
                    LearningErrorCode.INVALID_REFERENCE, f"{referenced_type} {referenced_id}"
                )
            if referenced.layer is not VendorLayer.GLOBAL:
                return _error(
                    LearningErrorCode.INVALID_REFERENCE,
                    f"{referenced_type} {referenced_id} is not in the global layer; "
                    "it must be shared and approved before a branch referencing it can be",
                )
        return None

    def _validate(
        self, entity_type: EntityType, fields: Mapping[str, object], for_create: bool
    ) -> LearningError | None:
        if entity_type not in _ENTITY_CLASSES:
            return _error(LearningErrorCode.UNKNOWN_ENTITY_TYPE, str(entity_type))
        # `Mapping`, never `dict`: a FrozenDict from a contract is not a dict subclass on
        # 3.15+ and this check would reject every correct caller (`docs/PRINCIPLES.md` §2.1).
        if not isinstance(fields, Mapping):
            return _error(LearningErrorCode.INVALID_CHANGE, "fields must be a mapping")
        if not fields:
            return _error(LearningErrorCode.INVALID_CHANGE, "no fields supplied")
        if for_create:
            missing = [f for f in _REQUIRED_FIELDS[entity_type] if not fields.get(f)]
            if missing:
                return _error(
                    LearningErrorCode.INVALID_CHANGE, f"missing required: {', '.join(missing)}"
                )
        if entity_type == "branch":
            corporation_id = fields.get("corporation_id")
            if corporation_id is not None and self._store.get("corporation", str(corporation_id)) is None:
                return _error(LearningErrorCode.INVALID_REFERENCE, f"corporation {corporation_id}")
            franchiser_id = fields.get("franchiser_id")
            if franchiser_id is not None and self._store.get("franchiser", str(franchiser_id)) is None:
                return _error(LearningErrorCode.INVALID_REFERENCE, f"franchiser {franchiser_id}")
        return None


def _field_names(cls: type) -> set[str]:
    return {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]


__all__ = [
    "EntityManager",
    "EntityStore",
    "InMemoryEntityStore",
    "entity_id_of",
    "entity_type_of",
]
