"""Synthetic family generator for Haven demos.

Generates a deterministic fake family (2 adults, 2 children) with plausible
addresses, phone numbers, and emails.  All data is completely synthetic.
No real personal data is used or generated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from haven.models import Family, FamilyMember, Identifier


def generate_family(*, seed: int = 42) -> Family:
    """Return a synthetic family for demo purposes.

    The data is deterministic for a given *seed* so that tests and demos
    are reproducible.  The seed controls the ``family_id`` UUID.
    """
    family_id = str(uuid.UUID(int=seed))

    last_name = "Castillo"
    address = "742 Evergreen Terrace"
    city = "Springfield"
    state = "IL"
    zip_code = "62704"

    parent1 = FamilyMember(
        first_name="Maria",
        last_name=last_name,
        role="parent",
        age=38,
        identifiers=[
            Identifier(kind="name", value=f"Maria {last_name}", sensitivity="low"),
            Identifier(kind="email", value="maria.castillo@example.com", sensitivity="high"),
            Identifier(kind="phone", value="(217) 555-0142", sensitivity="high"),
            Identifier(kind="city_state", value=f"{city}, {state}", sensitivity="low"),
            Identifier(kind="address", value=f"{address}, {city}, {state} {zip_code}", sensitivity="high"),
        ],
    )

    parent2 = FamilyMember(
        first_name="Daniel",
        last_name=last_name,
        role="parent",
        age=40,
        identifiers=[
            Identifier(kind="name", value=f"Daniel {last_name}", sensitivity="low"),
            Identifier(kind="email", value="d.castillo@example.com", sensitivity="high"),
            Identifier(kind="phone", value="(217) 555-0198", sensitivity="high"),
            Identifier(kind="alias", value="Dan Castillo", sensitivity="low"),
        ],
    )

    child1 = FamilyMember(
        first_name="Sofia",
        last_name=last_name,
        role="child",
        age=14,
        identifiers=[
            Identifier(kind="name", value=f"Sofia {last_name}", sensitivity="high"),
            Identifier(kind="school", value="Lincoln Middle School", sensitivity="high"),
        ],
    )

    child2 = FamilyMember(
        first_name="Lucas",
        last_name=last_name,
        role="child",
        age=10,
        identifiers=[
            Identifier(kind="name", value=f"Lucas {last_name}", sensitivity="high"),
            Identifier(kind="school", value="Washington Elementary", sensitivity="high"),
        ],
    )

    return Family(
        family_id=family_id,
        members=[parent1, parent2, child1, child2],
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        created_at=datetime.now(timezone.utc),
    )


def get_all_identifiers(family: Family) -> list[Identifier]:
    """Flatten all identifiers from every family member."""
    ids: list[Identifier] = []
    for member in family.members:
        ids.extend(member.identifiers)
    return ids


def get_search_identifiers(family: Family) -> list[Identifier]:
    """Return only the low-sensitivity identifiers safe for web searches.

    High-sensitivity identifiers (emails, phones, addresses, children's
    names/schools) are used only for *matching* results returned by the
    search, never sent as search queries themselves.
    """
    return [i for i in get_all_identifiers(family) if i.sensitivity == "low"]
