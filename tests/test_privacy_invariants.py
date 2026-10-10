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


def test_member_names_are_shown_because_the_local_console_is_not_egress(client):
    """Documented display policy, asserted so it cannot drift silently.

    ``Identifier.sensitivity`` governs *egress*: a high-sensitivity value must
    never leave for a model or a search API. Rendering a child's name in the
    operator's own console is not egress, and the parent already knows it. What
    must not follow the name is the sensitive context around it -- which is why
    the school identifier is redacted directly beside it.
    """
    html = client.get("/").text

    assert "Sofia Castillo" in html  # the operator's local view
    assert "Lincoln Middle School" not in html  # an Identifier value: redacted
    assert "maria.castillo@example.com" not in html


def test_family_api_redacts_high_sensitivity_values_by_default(client):
    """The API must not hand out what the UI it feeds refuses to display."""
    payload = client.get("/api/family").json()
    values = {
        ident["value"] for member in payload["members"] for ident in member["identifiers"]
    }

    assert "[REDACTED]" in values
    assert "maria.castillo@example.com" not in values
    assert "(217) 555-0142" not in values
    assert "742 Evergreen Terrace" not in values
    assert "Sofia Castillo" not in values
    # Low-sensitivity values stay visible: the operator needs them to confirm
    # which family is loaded.
    assert "Maria Castillo" in values
    assert "Springfield, IL" in values


def test_family_api_reveal_is_an_explicit_opt_in(client):
    """The raw view exists for the local operator and must be asked for."""
    payload = client.get("/api/family?reveal=true").json()
    values = {
        ident["value"] for member in payload["members"] for ident in member["identifiers"]
    }

    assert "maria.castillo@example.com" in values
    assert "Sofia Castillo" in values
    assert "[REDACTED]" not in values
