"""Synthetic family generator for Haven demos.

The demo family is deterministic and unmistakably fictional:

* surname ``Synthwell`` and the town ``Sampleville`` are invented;
* emails use the reserved ``example.com`` domain (RFC 2606);
* phone numbers use the reserved ``555-01xx`` fictional range;
* the ZIP code ``00000`` is not assigned to any real place.

The MVP scope is adults only. Children's names, schools and activities are
deliberately absent: the model can describe a ``child`` role for a future,
separately reviewed mode, but the demo never creates one.

Identifiers here are used for LOCAL matching only. No identifier -- whatever
its sensitivity label -- may be sent to Tavily, Token Factory or any other
third party; ``haven.privacy`` enforces that.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from haven.models import Family, FamilyMember, Identifier

LAST_NAME = "Synthwell"
STREET = "100 Fictional Way"
CITY = "Sampleville"
STATE = "CA"
ZIP_CODE = "00000"


def generate_family(*, seed: int = 42) -> Family:
    """Return the synthetic demo family.

    Deterministic for a given *seed*; the seed controls only ``family_id``.
    """
    family_id = str(uuid.UUID(int=seed))
    city_state = f"{CITY}, {STATE}"

    avery = FamilyMember(
        first_name="Avery",
        last_name=LAST_NAME,
        role="parent",
        age=41,
        identifiers=[
            Identifier(kind="name", value=f"Avery {LAST_NAME}", sensitivity="low"),
            Identifier(kind="city_state", value=city_state, sensitivity="low"),
            Identifier(kind="email", value="avery.synthwell@example.com", sensitivity="high"),
            Identifier(kind="phone", value="(555) 555-0142", sensitivity="high"),
            Identifier(
                kind="address",
                value=f"{STREET}, {CITY}, {STATE} {ZIP_CODE}",
                sensitivity="high",
            ),
        ],
    )

    jordan = FamilyMember(
        first_name="Jordan",
        last_name=LAST_NAME,
        role="parent",
        age=43,
        identifiers=[
            Identifier(kind="name", value=f"Jordan {LAST_NAME}", sensitivity="low"),
            Identifier(kind="alias", value=f"Jordy {LAST_NAME}", sensitivity="low"),
            Identifier(kind="city_state", value=city_state, sensitivity="low"),
            Identifier(kind="email", value="jordan.synthwell@example.com", sensitivity="high"),
            Identifier(kind="phone", value="(555) 555-0198", sensitivity="high"),
        ],
    )

    return Family(
        family_id=family_id,
        members=[avery, jordan],
        address=STREET,
        city=CITY,
        state=STATE,
        zip_code=ZIP_CODE,
        created_at=datetime.now(timezone.utc),
    )


def get_all_identifiers(family: Family) -> list[Identifier]:
    """Flatten all identifiers from every family member."""
    ids: list[Identifier] = []
    for member in family.members:
        ids.extend(member.identifiers)
    return ids


def get_search_identifiers(family: Family) -> list[Identifier]:
    """Low-sensitivity identifiers, for LOCAL display and matching only.

    Kept for API compatibility. Since the identifier-free redesign no
    identifier is ever used to build an outbound query; the name is historical.
    """
    return [i for i in get_all_identifiers(family) if i.sensitivity == "low"]


def redact_high_sensitivity(family: Family) -> Family:
    """Return a deep copy with every high-sensitivity identifier value hidden.

    The dashboard redacts these values, and the JSON API should not hand out
    what the UI it feeds refuses to show. The hosted demo URL is public, so
    the default is the redacted view even though the seed data is synthetic.
    """
    clone = family.model_copy(deep=True)
    clone.address = "[REDACTED]"
    for member in clone.members:
        for identifier in member.identifiers:
            if identifier.sensitivity == "high":
                identifier.value = "[REDACTED]"
    return clone
