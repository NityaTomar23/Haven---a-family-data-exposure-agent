"""The synthetic-family generator and the low/high sensitivity split.

The split is load-bearing: ``get_search_identifiers`` is the only sanctioned
source of outbound query text, so its filtering is asserted directly here.
"""

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


def test_family_has_two_parents_and_two_children(family: Family):
    roles = [member.role for member in family.members]
    assert roles.count("parent") == 2
    assert roles.count("child") == 2


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


def test_children_contribute_no_search_identifiers(family: Family):
    """Every child identifier is high-sensitivity, so children never drive a query."""
    child_values = {
        ident.value
        for member in family.members
        if member.role == "child"
        for ident in member.identifiers
    }
    assert child_values  # the fixture would be meaningless otherwise
    assert child_values.isdisjoint({i.value for i in get_search_identifiers(family)})


def test_emails_and_phones_are_never_search_identifiers(family: Family):
    kinds = {i.kind for i in get_search_identifiers(family)}
    assert "email" not in kinds
    assert "phone" not in kinds
    assert "address" not in kinds
    assert "school" not in kinds


def test_city_state_is_searchable_but_residential_address_is_not(family: Family):
    kinds = {i.kind for i in get_search_identifiers(family)}
    assert "city_state" in kinds
    assert "address" not in kinds


def test_seed_data_is_obviously_non_real(family: Family):
    """Nothing in the demo seed may resemble a reachable address or contact."""
    for ident in get_all_identifiers(family):
        if ident.kind == "email":
            assert ident.value.endswith("@example.com")
        if ident.kind == "phone":
            assert "555" in ident.value
