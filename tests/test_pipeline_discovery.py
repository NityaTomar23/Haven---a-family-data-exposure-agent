"""Stage 1: generic inventory discovery + purely local exact listing matching."""

from __future__ import annotations

import json

from haven import fixtures, pipeline
from haven.fixtures import SyntheticListing


def test_discover_inventory_classifies_generic_brokers_and_tags_coverage(monkeypatch):
    monkeypatch.setattr(
        "haven.research.search_inventory",
        lambda *, max_results=10: [
            {
                "url": "https://www.spokeo.com",
                "title": "Spokeo People Search",
                "content": "Find people by name and city.",
            },
            {
                "url": "https://www.example-newbroker.invalid",
                "title": "NewBroker Directory",
                "content": "Public background directory.",
            },
            {
                "url": "https://www.wikipedia.org/wiki/Data_broker",
                "title": "Data broker - Wikipedia",
                "content": "Encyclopedia article.",
            },
        ],
    )

    def fake_complete(*, tier, system, user, purpose="unspecified", **kwargs):
        assert tier == "nano"
        assert purpose == "classify_inventory_result"
        if "Spokeo" in user:
            return json.dumps(
                {
                    "is_broker": True,
                    "broker_name": "Spokeo",
                    "broker_type": "people_search",
                    "confidence": 0.92,
                }
            )
        if "NewBroker" in user:
            return json.dumps(
                {
                    "is_broker": True,
                    "broker_name": "NewBroker",
                    "broker_type": "data_broker",
                    "confidence": 0.78,
                }
            )
        return json.dumps({"is_broker": False, "confidence": 0.9})

    monkeypatch.setattr("haven.llm.complete", fake_complete)

    inventory = pipeline.discover_inventory()
    by_name = {entry.name: entry for entry in inventory}

    assert set(by_name) == {"Spokeo", "NewBroker"}
    assert by_name["Spokeo"].coverage == "local_fixture"
    assert by_name["Spokeo"].broker_type == "people_search"
    assert by_name["NewBroker"].coverage == "manual_only"


def test_discover_inventory_drops_low_confidence_and_malformed_json(monkeypatch):
    monkeypatch.setattr(
        "haven.research.search_inventory",
        lambda *, max_results=10: [
            {"url": "https://low.example", "title": "Low", "content": "Low match"},
            {"url": "https://bad.example", "title": "Bad", "content": "Broken JSON"},
        ],
    )

    responses = iter(
        [
            json.dumps(
                {
                    "is_broker": True,
                    "broker_name": "LowConf",
                    "broker_type": "other",
                    "confidence": 0.2,
                }
            ),
            "not valid json at all",
        ]
    )
    monkeypatch.setattr("haven.llm.complete", lambda **kwargs: next(responses))

    assert pipeline.discover_inventory(relevance_threshold=0.3) == []


def test_match_local_listings_distinguishes_verified_candidate_and_rejected(family):
    """Matching runs purely locally against the built-in fixtures with zero network calls."""
    exposures = pipeline.match_local_listings(family)

    by_broker = {e.source_name: e for e in exposures}

    # Built-in 7 fixtures: Spokeo, Whitepages, Radaris, FastPeopleSearch = verified;
    # BeenVerified = candidate; TruePeopleSearch = rejected; Intelius = not matched.
    assert by_broker["Spokeo"].match_status == "verified"
    assert by_broker["Whitepages"].match_status == "verified"
    assert by_broker["Radaris"].match_status == "verified"
    assert by_broker["FastPeopleSearch"].match_status == "verified"
    assert by_broker["BeenVerified"].match_status == "candidate"
    assert by_broker["TruePeopleSearch"].match_status == "rejected"
    assert "Intelius" not in by_broker

    # High-sensitivity matched identifiers must not leak verbatim into evidence_snippet
    for exp in exposures:
        for ident in exp.matched_identifiers:
            if ident.sensitivity == "high":
                assert ident.value not in exp.evidence_snippet


def test_match_local_listings_requires_more_than_city_state_alone(family):
    city_only = SyntheticListing(
        broker="CityOnly",
        url="https://cityonly.example/page",
        broker_type="people_search",
        location="Sampleville, CA",
        text="Directory of residents in Sampleville, CA 00000.",
    )
    assert pipeline.match_local_listings(family, [city_only]) == []


def test_discover_exposures_alias_delegates_to_local_matching(family):
    assert [(e.source_url, e.match_status) for e in pipeline.discover_exposures(family)] == [
        (e.source_url, e.match_status) for e in pipeline.match_local_listings(family)
    ]
    assert len(fixtures.load_listings()) == 7
