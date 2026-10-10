"""Stage 1: discovery and relevance classification.

The Tavily and Nemotron boundaries are replaced with fakes; what is under
test is the query construction, the threshold/dedup logic, and the
graceful degradation when the model returns junk.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from haven import pipeline
from haven.models import Family, Identifier

from conftest import high_sensitivity_values


@pytest.fixture
def captured_queries(monkeypatch) -> list[tuple[str, int]]:
    """Replace Tavily search with a recorder that returns no results."""
    calls: list[tuple[str, int]] = []

    def fake_search(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        calls.append((query, max_results))
        return []

    monkeypatch.setattr("haven.research.search_brokers", fake_search)
    return calls


@pytest.fixture
def fake_complete(monkeypatch):
    """Replace the LLM with a scripted responder; returns the captured calls."""

    def _install(payload: Any):
        calls: list[dict[str, Any]] = []

        def fake_complete(**kwargs):
            calls.append(kwargs)
            if callable(payload):
                return payload(kwargs)
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr("haven.llm.complete", fake_complete)
        return calls

    return _install


def _relevant(**overrides) -> str:
    body = {
        "relevant": True,
        "confidence": 0.9,
        "broker_type": "people_search",
        "source_name": "Spokeo",
        "evidence": "listing matches the search terms",
    }
    body.update(overrides)
    return json.dumps(body)


# ── Query construction ─────────────────────────────────────────────────


def test_discovery_issues_queries_for_every_low_sensitivity_identifier(
    family: Family, captured_queries
):
    pipeline.discover_exposures(family, max_search_results=7)
    assert len(captured_queries) == 7
    assert all(max_results == 7 for _, max_results in captured_queries)


def test_discovery_query_text_is_expected(family: Family, captured_queries):
    pipeline.discover_exposures(family)
    queries = [q for q, _ in captured_queries]

    assert '"Maria Castillo" people search' in queries
    assert '"Maria Castillo" public records' in queries
    assert '"Daniel Castillo" people search' in queries
    assert '"Dan Castillo" people search' in queries
    assert '"Maria Castillo" Springfield, IL data broker' in queries
    assert '"Daniel Castillo" Springfield, IL data broker' in queries


def test_discovery_sends_no_high_sensitivity_value(family: Family, captured_queries):
    pipeline.discover_exposures(family)
    for query, _ in captured_queries:
        for secret in high_sensitivity_values(family):
            assert secret not in query, f"leaked {secret!r} in query {query!r}"


def test_discovery_sends_no_child_or_school_text(family: Family, captured_queries):
    pipeline.discover_exposures(family)
    joined = " ".join(q for q, _ in captured_queries)
    for forbidden in ("Sofia", "Lucas", "Lincoln Middle School", "Washington Elementary"):
        assert forbidden not in joined


# ── Classification, dedup, thresholds ──────────────────────────────────


def test_relevant_result_becomes_an_exposure(family: Family, monkeypatch, fake_complete):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [
            {
                "url": "https://spokeo.example/p/maria",
                "title": "Maria Castillo — Spokeo",
                "content": "Maria Castillo, Springfield IL",
            }
        ],
    )
    fake_complete(_relevant())

    exposures = pipeline.discover_exposures(family)

    assert len(exposures) == 1
    exposure = exposures[0]
    assert exposure.source_url == "https://spokeo.example/p/maria"
    assert exposure.source_name == "Spokeo"
    assert exposure.broker_type == "people_search"
    assert exposure.confidence == pytest.approx(0.9)
    assert exposure.evidence_snippet == "listing matches the search terms"


def test_identical_urls_are_deduplicated(family: Family, monkeypatch, fake_complete):
    """Each identifier fires its own query; the same listing must appear once."""
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://same.example/one", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant())

    exposures = pipeline.discover_exposures(family)

    assert len(exposures) == 1


def test_irrelevant_result_is_discarded(family: Family, monkeypatch, fake_complete):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant(relevant=False))

    assert pipeline.discover_exposures(family) == []


def test_low_confidence_result_is_discarded(family: Family, monkeypatch, fake_complete):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant(confidence=0.2))

    assert pipeline.discover_exposures(family, relevance_threshold=0.3) == []


def test_confidence_at_the_threshold_is_kept(family: Family, monkeypatch, fake_complete):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant(confidence=0.3))

    assert len(pipeline.discover_exposures(family, relevance_threshold=0.3)) == 1


def test_overconfident_model_is_clamped(family: Family, monkeypatch, fake_complete):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant(confidence=1.7))

    exposures = pipeline.discover_exposures(family)

    assert exposures[0].confidence == 1.0


def test_source_name_falls_back_to_the_result_title(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [
            {"url": "https://example.test/x", "title": "Some Broker", "content": "C"}
        ],
    )
    fake_complete(json.dumps({"relevant": True, "confidence": 0.8}))

    exposures = pipeline.discover_exposures(family)

    assert exposures[0].source_name == "Some Broker"
    assert exposures[0].broker_type == "other"


def test_unknown_broker_type_drops_the_result_instead_of_crashing(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant(broker_type="scraped_list"))

    assert pipeline.discover_exposures(family) == []


# ── Graceful degradation ───────────────────────────────────────────────


def test_model_exception_drops_the_result(family: Family, monkeypatch, fake_complete):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(RuntimeError("nebius unavailable"))

    assert pipeline.discover_exposures(family) == []


def test_unparseable_model_output_drops_the_result(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete("I am unable to classify this page.")

    assert pipeline.discover_exposures(family) == []


def test_non_numeric_confidence_drops_the_result(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant(confidence="high"))

    assert pipeline.discover_exposures(family) == []


def test_search_failure_propagates_to_the_caller(family: Family, monkeypatch):
    """A broken search backend is an operator problem, not a per-result skip."""

    def boom(query, **kwargs):
        raise RuntimeError("tavily 429")

    monkeypatch.setattr("haven.research.search_brokers", boom)

    with pytest.raises(RuntimeError, match="tavily 429"):
        pipeline.discover_exposures(family)


def test_result_without_a_url_is_still_classified(family: Family, monkeypatch, fake_complete):
    """A missing url yields an empty string key rather than a crash."""
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"title": "T", "content": "C"}],
    )
    fake_complete(_relevant())

    exposures = pipeline.discover_exposures(family)

    assert len(exposures) == 1
    assert exposures[0].source_url == ""


# ── Matched identifiers ────────────────────────────────────────────────


def test_matched_identifiers_are_low_sensitivity_only_and_capped(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant())

    exposures = pipeline.discover_exposures(family)

    matched = exposures[0].matched_identifiers
    assert 0 < len(matched) <= 3
    assert all(ident.sensitivity == "low" for ident in matched)


def test_classifier_prompt_redacts_high_sensitivity_values(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    calls = fake_complete(_relevant())

    pipeline.discover_exposures(family)

    assert calls
    for call in calls:
        prompt = call["user"]
        for secret in high_sensitivity_values(family):
            assert secret not in prompt
        assert "[REDACTED]" in prompt


def test_classifier_uses_the_nano_tier_and_low_temperature(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    calls = fake_complete(_relevant())

    pipeline.discover_exposures(family)

    assert all(call["tier"] == "nano" for call in calls)
    assert all(call["temperature"] <= 0.2 for call in calls)
    assert all(call["purpose"] == "classify_search_result" for call in calls)


def test_snippet_is_truncated_before_reaching_the_model(
    family: Family, monkeypatch, fake_complete
):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [
            {"url": "https://example.test/x", "title": "T", "content": "Z" * 5000}
        ],
    )
    calls = fake_complete(_relevant())

    pipeline.discover_exposures(family)

    assert calls
    assert all(call["user"].count("Z") == 500 for call in calls)


def test_identifier_kinds_are_visible_to_the_classifier(family: Family, monkeypatch, fake_complete):
    """Kinds are safe to send; the model needs them to judge a match."""
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    calls = fake_complete(_relevant())

    pipeline.discover_exposures(family)

    prompt = calls[0]["user"]
    assert "- name: Maria Castillo" in prompt
    assert "- alias: Dan Castillo" in prompt


def test_empty_result_set_yields_no_exposures(family: Family, captured_queries):
    assert pipeline.discover_exposures(family) == []


def test_exposure_identifiers_are_pydantic_instances(family: Family, monkeypatch, fake_complete):
    monkeypatch.setattr(
        "haven.research.search_brokers",
        lambda q, **kw: [{"url": "https://example.test/x", "title": "T", "content": "C"}],
    )
    fake_complete(_relevant())

    exposures = pipeline.discover_exposures(family)

    assert all(isinstance(i, Identifier) for i in exposures[0].matched_identifiers)
