"""The project's central promise, asserted end to end.

Haven claims that high-sensitivity identifiers never leave the process as
outbound content.  These tests drive the real pipeline with fake providers,
record everything that would have crossed the network boundary, and assert
that no high-sensitivity value is in it.

Two further tests document behaviour that is *not* redacted today.  They are
written to be honest about the current state rather than to bless it.
"""

from __future__ import annotations

import json

import pytest

from haven import pipeline
from haven.models import Family

from conftest import high_sensitivity_values


@pytest.fixture
def recorded_outbound(monkeypatch):
    """Drive a full pipeline run while recording every outbound payload."""
    outbound: list[tuple[str, str]] = []

    def fake_search(query: str, *, max_results: int = 10):
        outbound.append(("tavily.search", query))
        return [
            {
                "url": "https://spokeo.example/p/maria-castillo",
                "title": "Maria Castillo — Spokeo",
                "content": "Maria Castillo, Springfield IL. Relatives: none listed.",
            }
        ]

    def fake_optout(site_name: str):
        outbound.append(("tavily.search", site_name))
        return [{"url": "https://spokeo.example/optout", "content": "opt out here"}]

    def fake_extract(url: str):
        outbound.append(("tavily.extract", url))
        return {"raw_content": "Use the opt-out form, then confirm by email."}

    def fake_complete(**kwargs):
        outbound.append((f"llm.{kwargs['tier']}.system", kwargs["system"]))
        outbound.append((f"llm.{kwargs['tier']}.user", kwargs["user"]))
        if kwargs["purpose"] == "classify_search_result":
            return json.dumps(
                {
                    "relevant": True,
                    "confidence": 0.92,
                    "broker_type": "people_search",
                    "source_name": "Spokeo",
                    "evidence": "listing matches the searched name and city",
                }
            )
        if kwargs["purpose"] == "extract_optout_procedure":
            return json.dumps(
                {
                    "method": "web_form",
                    "action_url": "https://spokeo.example/optout",
                    "required_evidence": ["Government-issued ID"],
                    "statutory_deadline_days": 45,
                    "jurisdiction": "CCPA",
                    "steps": ["Open the opt-out form", "Submit the listing URL"],
                }
            )
        return "DRAFT — for human review only. Remove the listing at the URL above."

    monkeypatch.setattr("haven.research.search_brokers", fake_search)
    monkeypatch.setattr("haven.research.search_optout_procedure", fake_optout)
    monkeypatch.setattr("haven.research.extract_page", fake_extract)
    monkeypatch.setattr("haven.llm.complete", fake_complete)

    def _run(family: Family):
        state = pipeline.run_pipeline(family)
        assert state.exposures and state.procedures and state.actions
        return state

    return _run, outbound


def test_full_run_sends_no_high_sensitivity_value(family: Family, recorded_outbound):
    run, outbound = recorded_outbound

    run(family)

    assert len(outbound) >= 20, "the run must actually exercise every channel"
    for channel, payload in outbound:
        for secret in high_sensitivity_values(family):
            assert secret not in payload, f"{channel} leaked {secret!r}"


def test_full_run_redacts_high_sensitivity_markers_for_the_model(
    family: Family, recorded_outbound
):
    run, outbound = recorded_outbound

    run(family)

    llm_payloads = [p for c, p in outbound if c.startswith("llm.")]
    assert llm_payloads
    assert any("[REDACTED]" in payload for payload in llm_payloads)


def test_search_queries_carry_no_email_phone_or_address_shapes(
    family: Family, monkeypatch
):
    """Every identifier containing digits or '@' is high-sensitivity, so a
    query that contains one is by definition a leak."""
    queries: list[str] = []

    def fake_search(query: str, *, max_results: int = 10):
        queries.append(query)
        return []

    monkeypatch.setattr("haven.research.search_brokers", fake_search)

    pipeline.discover_exposures(family)

    assert queries
    for query in queries:
        assert "@" not in query
        assert not any(character.isdigit() for character in query)


def test_no_child_identifier_reaches_a_search_query(family: Family, monkeypatch):
    queries: list[str] = []

    def fake_search(query: str, *, max_results: int = 10):
        queries.append(query)
        return []

    monkeypatch.setattr("haven.research.search_brokers", fake_search)

    pipeline.discover_exposures(family)

    child_text = {
        ident.value
        for member in family.members
        if member.role == "child"
        for ident in member.identifiers
    }
    for query in queries:
        for value in child_text:
            assert value not in query


def test_evidence_panel_states_where_the_data_comes_from(client):
    html = client.get("/").text

    assert "OpenShell OCSF audit logs" in html
    assert "NOT from the agent" in html


# ── Dashboard redaction ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "secret",
    [
        "maria.castillo@example.com",
        "d.castillo@example.com",
        "(217) 555-0142",
        "(217) 555-0198",
        "742 Evergreen Terrace",
        "Lincoln Middle School",
        "Washington Elementary",
    ],
)
def test_dashboard_never_prints_a_high_sensitivity_value(client, secret: str):
    assert secret not in client.get("/").text


def test_dashboard_marks_redacted_identifiers_explicitly(client):
    assert "[REDACTED" in client.get("/").text


@pytest.mark.xfail(
    reason=(
        "FamilyMember.first_name/last_name are rendered in the family-card heading, "
        "so a child's name is redacted in the identifier list and then displayed "
        "anyway in the card title. Fixing this needs a display policy decision."
    ),
    strict=False,
)
def test_children_names_are_not_rendered_in_plain_text(client):
    assert "Sofia Castillo" not in client.get("/").text


def test_family_api_returns_unredacted_identifier_values(client):
    """Documents a gap, not a requirement.

    The dashboard template redacts high-sensitivity identifier values, but the
    endpoint it reads from returns them verbatim.  That is fine while the app is
    a localhost demo and becomes a real problem the moment it is exposed.
    """
    payload = client.get("/api/family").json()
    values = {
        ident["value"] for member in payload["members"] for ident in member["identifiers"]
    }

    assert "maria.castillo@example.com" in values
    assert "Sofia Castillo" in values
