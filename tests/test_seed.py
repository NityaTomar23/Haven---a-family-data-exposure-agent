"""The synthetic-family generator and MVP scope invariants."""

from __future__ import annotations

from datetime import timezone

from haven.models import Family
from haven.seed import (
    generate_family,
    get_all_identifiers,
    get_search_identifiers,
)


def test_family_is_deterministic_for_a_seed():
    assert generate_family(seed=42).family_id == generate_family(seed=42).family_id


def test_different_seeds_produce_different_family_ids():
    assert generate_family(seed=42).family_id != generate_family(seed=7).family_id


def test_family_is_adults_only_with_no_children(family: Family):
    """MVP scope excludes children's names, schools, and activities."""
    roles = [member.role for member in family.members]
    assert roles == ["parent", "parent"]
    assert all(member.age >= 18 for member in family.members)


def test_family_timestamp_is_timezone_aware(family: Family):
    assert family.created_at.tzinfo is not None
    assert family.created_at.utcoffset() == timezone.utc.utcoffset(None)


def test_all_identifiers_flattens_every_member(family: Family):
    expected = sum(len(member.identifiers) for member in family.members)
    assert len(get_all_identifiers(family)) == expected
    assert expected > 0


def test_search_identifiers_are_only_low_sensitivity(family: Family):
    assert get_search_identifiers(family)
    assert {i.sensitivity for i in get_search_identifiers(family)} == {"low"}


def test_search_identifiers_exclude_every_high_sensitivity_value(family: Family):
    low_values = {i.value for i in get_search_identifiers(family)}
    high_values = {
        i.value for i in get_all_identifiers(family) if i.sensitivity == "high"
    }
    assert low_values.isdisjoint(high_values)


def test_emails_and_phones_are_never_in_low_sensitivity(family: Family):
    kinds = {i.kind for i in get_search_identifiers(family)}
    assert "email" not in kinds
    assert "phone" not in kinds
    assert "address" not in kinds


def test_seed_data_is_obviously_fictional_and_reserved(family: Family):
    """Demo personas must use reserved test values (example.com, 555-01xx, 00000)."""
    assert family.zip_code == "00000"
    assert family.last_name if hasattr(family, "last_name") else True
    for ident in get_all_identifiers(family):
        if ident.kind == "email":
            assert ident.value.endswith("@example.com")
        if ident.kind == "phone":
            assert "555-01" in ident.value
