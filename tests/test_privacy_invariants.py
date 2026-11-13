"""Privacy invariants: outbound payload gate, redaction, and non-transmission.

Haven's core privacy contract:

1. Every outbound payload to Tavily or Token Factory passes through
   ``haven.privacy.check()`` *before* the SDK client is even constructed.
2. Protected terms (all Synthwell identifiers, surname, phones in any format,
   emails & local parts, street address, city/state, fixture listing URLs,
   and fixture listing sentences >= 24 chars) raise ``PayloadBlocked`` without
   echoing the matched value.
3. No protected value appears in any outbound search query or LLM prompt during
   a full ``run_pipeline()`` run.
4. High-sensitivity identifiers never appear in rendered dashboard HTML or
   ``/api/family`` unless ``?reveal=true`` is explicitly requested.
"""

from __future__ import annotations

import json
import re

import pytest

from haven import api, fixtures, llm, pipeline, privacy, research
from haven.models import PipelineState

from conftest import high_sensitivity_values, make_action, make_exposure, make_procedure


# ── Outbound payload gate (haven.privacy) ──────────────────────────────


def test_privacy_gate_fails_closed_even_before_register():
    """Without register(), the gate still protects the built-in demo family and fixtures."""
    with pytest.raises(privacy.PayloadBlocked) as exc_info:
        privacy.check("tavily_search", "Avery Synthwell Spokeo")

    assert exc_info.value.channel == "tavily_search"
    assert "Synthwell" not in str(exc_info.value)
    assert "Avery" not in str(exc_info.value)


def test_privacy_gate_blocks_every_family_identifier_and_never_echoes_secret(family):
    privacy.register(family, fixtures.load_listings())

    for member in family.members:
        for ident in member.identifiers:
            with pytest.raises(privacy.PayloadBlocked) as exc_info:
                privacy.check("token_factory", f"Search for {ident.value} on broker")
            msg = str(exc_info.value)
            assert ident.value not in msg

    # Surname on its own
    with pytest.raises(privacy.PayloadBlocked):
        privacy.check("tavily_search", "people search Synthwell")

    # Phone numbers in stripped or punctuated forms
    for phone_variant in ["5550142", "555.0142", "555 0198"]:
        with pytest.raises(privacy.PayloadBlocked):
            privacy.check("token_factory", f"Call {phone_variant}")

    # Email local parts
    with pytest.raises(privacy.PayloadBlocked):
        privacy.check("token_factory", "Account avery.synthwell registered")


def test_privacy_gate_blocks_fixture_urls_and_sentences(family):
    listings = fixtures.load_listings()
    privacy.register(family, listings)

    first = listings[0]
    with pytest.raises(privacy.PayloadBlocked) as url_exc:
        privacy.check("tavily_extract", first.url)
    assert first.url not in str(url_exc.value)

    # Extract a long sentence (>24 chars) from a fixture listing text
    long_sentence = next(s.strip() for s in first.text.split(".") if len(s.strip()) >= 24)
    with pytest.raises(privacy.PayloadBlocked):
        privacy.check("token_factory", f"Analyze this text: {long_sentence}")

    assert len(privacy.blocked_events()) == 2


def test_privacy_gate_allows_generic_broker_and_optout_queries(family):
    privacy.register(family, fixtures.load_listings())

    # First names on their own (e.g. Jordan) or generic queries should pass
    privacy.check("tavily_search", "Spokeo opt out removal request")
    privacy.check("token_factory", "Draft template for [FULL_NAME] at [LISTING_URL]")
    assert privacy.blocked_events() == []


def test_research_and_llm_invoke_privacy_gate_before_network_client(monkeypatch):
    """If an outbound call contains PII, _get_client is never even called."""
    monkeypatch.setenv("HAVEN_PROVIDER_MODE", "live")
    client_called = False

    def fail_if_reached():
        nonlocal client_called
        client_called = True
        raise AssertionError("_get_client should not run after PayloadBlocked")

    monkeypatch.setattr("haven.research._get_client", fail_if_reached)
    monkeypatch.setattr("haven.llm._get_client", fail_if_reached)

    with pytest.raises(privacy.PayloadBlocked):
        research.search_brokers("Avery Synthwell Sampleville")

    with pytest.raises(privacy.PayloadBlocked):
        research.extract_page("https://spokeo.example/listing/avery-synthwell-ca")

    with pytest.raises(privacy.PayloadBlocked):
        llm.complete(
            tier="super",
            system="You are drafting data removal requests.",
            user="Remove avery.synthwell@example.com from Spokeo",
            purpose="draft_removal_request",
        )

    assert client_called is False


# ── End-to-end outbound prompt & search cleanliness ────────────────────


def test_full_pipeline_never_leaks_identifiers_in_any_outbound_payload(family, monkeypatch):
    captured_queries: list[str] = []
    captured_extracts: list[str] = []
    captured_prompts: list[str] = []

    def fake_search_inventory(*, max_results=10):
        for q in research.INVENTORY_QUERIES:
            privacy.check("tavily_search", q)
            captured_queries.append(q)
        return [
            {
                "url": "https://www.spokeo.com/about",
                "title": "Spokeo People Search",
                "content": "Spokeo aggregates public profiles.",
            }
        ]

    def fake_search_optout(site_name: str):
        q = f"{site_name} opt out privacy removal request"
        privacy.check("tavily_search", q)
        captured_queries.append(q)
        return [{"url": f"https://{site_name.lower()}.example/optout", "content": "Opt out steps."}]

    def fake_extract(url: str):
        privacy.check("tavily_extract", url)
        captured_extracts.append(url)
        return {"url": url, "raw_content": "Submit the listing URL on our opt-out web form."}

    def fake_complete(*, tier, system, user, purpose="unspecified", **kwargs):
        privacy.check("token_factory", system, user)
        captured_prompts.append(f"{system}\n{user}")
        if purpose == "classify_inventory_result":
            return json.dumps(
                {
                    "is_broker": True,
                    "broker_name": "Spokeo",
                    "broker_type": "people_search",
                    "confidence": 0.9,
                }
            )
        if purpose == "extract_optout_procedure":
            return json.dumps(
                {
                    "method": "web_form",
                    "action_url": "https://www.spokeo.com/optout",
                    "required_evidence": ["Listing URL"],
                    "statutory_deadline_days": 45,
                    "deadline_source_url": "https://oag.ca.gov/privacy/ccpa",
                    "service_target_days": 3,
                    "jurisdiction": "CCPA",
                    "steps": ["Paste listing URL", "Submit form"],
                }
            )
        if purpose == "synthesize_removal_strategy":
            return "Prioritize Spokeo, Whitepages, Radaris, FastPeopleSearch, then BeenVerified."
        return "DRAFT template for [FULL_NAME] at [LISTING_URL] ([EMAIL], [PHONE], [ADDRESS])."

    monkeypatch.setattr("haven.research.search_inventory", fake_search_inventory)
    monkeypatch.setattr("haven.research.search_optout_procedure", fake_search_optout)
    monkeypatch.setattr("haven.research.extract_page", fake_extract)
    monkeypatch.setattr("haven.llm.complete", fake_complete)

    state = pipeline.run_pipeline(family)

    assert len(state.exposures) >= 5
    all_outbound = "\n".join(captured_queries + captured_extracts + captured_prompts)
    assert privacy.find_violation(all_outbound) is None
    for secret in high_sensitivity_values(family):
        assert secret not in all_outbound
    assert "Synthwell" not in all_outbound


# ── Dashboard & /api/family redaction ──────────────────────────────────


def test_dashboard_and_family_endpoint_redact_high_sensitivity_values(client, family):
    state = PipelineState(
        family=family,
        exposures=[make_exposure()],
        procedures=[make_procedure(make_exposure())],
        actions=[make_action(make_exposure(), make_procedure(make_exposure()))],
    )
    api._set_state(state)

    html = client.get("/").text
    family_json = client.get("/api/family").text

    for secret in high_sensitivity_values(family):
        assert secret not in html, f"High-sensitivity identifier {secret!r} appeared unredacted on dashboard"
        assert secret not in family_json, f"High-sensitivity identifier {secret!r} appeared unredacted in /api/family"

    # Full street address and phone digits must also be redacted
    assert family.address not in html
    assert family.address not in family_json
    assert re.search(r"555[-.]0142", html) is None
    assert re.search(r"555[-.]0198", html) is None

    # Explicit ?reveal=true opt-in does reveal the family's high-sensitivity values
    revealed_json = client.get("/api/family?reveal=true").text
    for secret in high_sensitivity_values(family):
        assert secret in revealed_json
