"""The read-side vendor directory (`v3-deepdive-26-architect-api.md` §7).

Two properties matter here and both are about boundaries rather than search quality: a
search never leaks another user's `LOCAL` entities, and it never pretends to do Matching's
fuzzy scoring — a genuinely different string does not resolve, however close it looks.
"""

from __future__ import annotations

import asyncio

from core.architect.temporal_learning.entities import EntityManager
from core.architect.temporal_learning.layering import LayeringService
from core.architect.temporal_learning.moderation_queue import ModerationQueue
from core.architect.vendor_directory.aliases import AliasIndex
from core.architect.vendor_directory.directory import VendorDirectory


def _directory():
    entities = EntityManager()
    queue = ModerationQueue(entities)
    layering = LayeringService(entities, queue)
    aliases = AliasIndex()
    return entities, layering, VendorDirectory(entities, aliases), aliases


def test_search_finds_a_global_corporation_by_name():
    entities, layering, directory, _ = _directory()
    asyncio.run(
        layering.staff_create_global(
            "corporation", {"name": "Metro Mart Inc.", "corporate_tin": "123-456-789"},
            staff_user_id="staff-1",
        )
    )
    result = directory.search("metro mart")
    assert [r.name for r in result.records] == ["Metro Mart Inc."]


def test_search_finds_by_alias_and_by_tin():
    entities, layering, directory, aliases = _directory()
    asyncio.run(
        layering.staff_create_global(
            "corporation", {"name": "Metro Mart Inc.", "corporate_tin": "123-456-789"},
            staff_user_id="staff-1",
        )
    )
    corporation_id = entities.store.all_of("corporation")[0].corporation_id
    aliases.add("MM Supermarket", corporation_id)

    assert directory.search("MM Supermarket").records[0].corporation_id == corporation_id
    assert directory.search("123456789").records[0].corporation_id == corporation_id


def test_a_local_entity_is_never_returned_to_another_user():
    entities, _, directory, _ = _directory()
    entities.create(
        "corporation", {"name": "Aling Nena Store", "corporate_tin": "1"}, actor_user_id="user-1"
    )
    assert directory.search("aling nena", user_id="user-1").records
    assert directory.search("aling nena", user_id="user-2").records == ()
    assert directory.search("aling nena").records == ()


def test_branch_count_is_carried_not_the_branch_list():
    entities, layering, directory, _ = _directory()
    asyncio.run(
        layering.staff_create_global(
            "corporation", {"name": "Chain", "corporate_tin": "1"}, staff_user_id="staff-1"
        )
    )
    corporation_id = entities.store.all_of("corporation")[0].corporation_id
    for address in ("1 A St", "2 B St"):
        entities.create(
            "branch", {"corporation_id": corporation_id, "address": address},
            actor_user_id="user-1",
        )
    record = directory.search("chain").records[0]
    assert record.branch_count == 2


def test_search_does_not_fuzzy_match():
    _, layering, directory, _ = _directory()
    asyncio.run(
        layering.staff_create_global(
            "corporation", {"name": "Jollibee Foods Corporation", "corporate_tin": "1"},
            staff_user_id="staff-1",
        )
    )
    assert directory.search("jolibee").records == ()
    assert directory.search("jollibee").records  # a real substring, not a fuzzy hit


def test_exact_matches_are_ordered_ahead_of_substring_matches():
    _, layering, directory, _ = _directory()
    for name in ("Mart", "Metro Mart Express"):
        asyncio.run(
            layering.staff_create_global(
                "corporation", {"name": name, "corporate_tin": "1"}, staff_user_id="staff-1"
            )
        )
    assert directory.search("mart").records[0].name == "Mart"
