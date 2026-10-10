"""Stages 2 and 3: opt-out procedure extraction and removal drafting."""

from __future__ import annotations

import json
from typing import Any

import pytest

from haven import llm, pipeline
from haven.models import Exposure, Family, RemovalProcedure

from conftest import make_exposure, make_procedure


def _procedure_json(**overrides) -> str:
    body = {
        "method": "web_form",
        "action_url": "https://spokeo.example/optout",
        "required_evidence": ["Government-issued ID"],
        "statutory_deadline_days": 45,
        "jurisdiction": "CCPA",
        "steps": ["Open the opt-out page", "Paste the listing URL", "Submit"],
    }
    body.update(overrides)
    return json.dumps(body)


@pytest.fixture
def fake_search(monkeypatch):
    """Replace the opt-out search; returns the captured queries."""

    def _install(results: list[dict[str, Any]] | Exception):
        calls: list[str] = []

        def fake(site_name: str):
            calls.append(site_name)
            if isinstance(results, Exception):
                raise results
            return results

        monkeypatch.setattr("haven.research.search_optout_procedure", fake)
        return calls

    return _install


@pytest.fixture
def fake_extract(monkeypatch):
    """Replace Tavily Extract; returns the captured URLs."""

    def _install(payload: Any):
        calls: list[str] = []

        def fake(url: str):
            calls.append(url)
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr("haven.research.extract_page", fake)
        return calls

    return _install


@pytest.fixture
def fake_complete(monkeypatch):
    def _install(payload: Any):
        calls: list[dict[str, Any]] = []

        def fake(**kwargs):
            calls.append(kwargs)
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr("haven.llm.complete", fake)
        return calls

    return _install


# ── Stage 2: procedure extraction ──────────────────────────────────────


def test_procedure_is_synthesised_from_the_best_result(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    fake_search([{"url": "https://spokeo.example/optout", "content": "search snippet"}])
    extract_urls = fake_extract({"raw_content": "Full opt-out instructions ..."})
    fake_complete(_procedure_json())

    procedure = pipeline._extract_single_procedure(exposure)

    assert procedure is not None
    assert procedure.exposure_id == exposure.id
    assert procedure.method == "web_form"
    assert procedure.action_url == "https://spokeo.example/optout"
    assert procedure.required_evidence == ["Government-issued ID"]
    assert procedure.statutory_deadline_days == 45
    assert procedure.jurisdiction == "CCPA"
    assert len(procedure.steps) == 3
    assert procedure.source_url == "https://spokeo.example/optout"
    assert extract_urls == ["https://spokeo.example/optout"]


def test_optout_search_is_scoped_to_the_site_name(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    calls = fake_search([{"url": "https://spokeo.example/optout", "content": "c"}])
    fake_extract({"raw_content": "text"})
    fake_complete(_procedure_json())

    pipeline._extract_single_procedure(exposure)

    assert calls == ["Spokeo"]


def test_no_search_results_falls_back_to_a_manual_procedure(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    fake_search([])
    extract_urls = fake_extract({"raw_content": "never used"})
    llm_calls = fake_complete(_procedure_json())

    procedure = pipeline._extract_single_procedure(exposure)

    assert procedure is not None
    assert procedure.method == "manual_only"
    assert procedure.action_url == exposure.source_url
    assert procedure.source_url == exposure.source_url
    assert len(procedure.steps) == 4
    assert extract_urls == []
    assert llm_calls == []


def test_extract_failure_falls_back_to_the_search_snippet(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    fake_search([{"url": "https://spokeo.example/optout", "content": "SNIPPETTEXT"}])
    fake_extract(RuntimeError("extract 502"))
    calls = fake_complete(_procedure_json())

    procedure = pipeline._extract_single_procedure(exposure)

    assert procedure is not None
    assert procedure.method == "web_form"
    assert "SNIPPETTEXT" in calls[0]["user"]


def test_model_failure_falls_back_to_a_manual_procedure(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    fake_search([{"url": "https://spokeo.example/optout", "content": "c"}])
    fake_extract({"raw_content": "text"})
    fake_complete(RuntimeError("token factory 503"))

    procedure = pipeline._extract_single_procedure(exposure)

    assert procedure is not None
    assert procedure.method == "manual_only"
    assert procedure.source_url == exposure.source_url


def test_unparseable_procedure_output_degrades_to_defaults(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    """The model returned prose, so every field must fall back rather than raise."""
    fake_search([{"url": "https://spokeo.example/optout", "content": "c"}])
    fake_extract({"raw_content": "text"})
    fake_complete("I could not find an opt-out procedure on that page.")

    procedure = pipeline._extract_single_procedure(exposure)

    assert procedure is not None
    assert procedure.method == "manual_only"
    assert procedure.action_url is None
    assert procedure.required_evidence == []
    assert procedure.statutory_deadline_days is None
    assert procedure.jurisdiction is None
    assert procedure.steps == ["Visit the site and follow their opt-out process"]


def test_procedure_extraction_uses_the_super_tier(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    fake_search([{"url": "https://spokeo.example/optout", "content": "c"}])
    fake_extract({"raw_content": "text"})
    calls = fake_complete(_procedure_json())

    pipeline._extract_single_procedure(exposure)

    assert calls[0]["tier"] == "super"
    assert calls[0]["purpose"] == "extract_optout_procedure"


def test_page_content_is_truncated_before_reaching_the_model(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    fake_search([{"url": "https://spokeo.example/optout", "content": "c"}])
    fake_extract({"raw_content": "Q" * 9000})
    calls = fake_complete(_procedure_json())

    pipeline._extract_single_procedure(exposure)

    assert calls[0]["user"].count("Q") == 3000


def test_missing_raw_content_falls_back_to_an_empty_string(
    exposure: Exposure, fake_search, fake_extract, fake_complete
):
    fake_search([{"url": "https://spokeo.example/optout", "content": "c"}])
    fake_extract({"url": "https://spokeo.example/optout"})
    calls = fake_complete(_procedure_json())

    procedure = pipeline._extract_single_procedure(exposure)

    assert procedure is not None
    assert calls  # the model was still consulted


def test_procedures_are_extracted_for_every_exposure(
    fake_search, fake_extract, fake_complete
):
    exposures = [make_exposure(exposure_id=f"e{i}", source_url=f"https://s{i}.example") for i in range(3)]
    fake_search([{"url": "https://optout.example", "content": "c"}])
    fake_extract({"raw_content": "text"})
    fake_complete(_procedure_json())

    procedures = pipeline.extract_optout_procedures(exposures)

    assert [p.exposure_id for p in procedures] == ["e0", "e1", "e2"]


def test_fallback_procedure_points_at_the_listing(exposure: Exposure):
    procedure = pipeline._fallback_procedure(exposure)

    assert isinstance(procedure, RemovalProcedure)
    assert procedure.action_url == exposure.source_url
    assert any(exposure.source_url in step for step in procedure.steps)


# ── Stage 3: drafting ──────────────────────────────────────────────────


def _draft_and_capture(family: Family, exposure: Exposure, procedure, payload: Any, monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr("haven.llm.complete", fake)
    action = pipeline._draft_single_request(family, exposure, procedure)
    return action, calls


def test_draft_uses_the_first_parent_as_requestor(
    family: Family, exposure: Exposure, procedure, monkeypatch
):
    action, calls = _draft_and_capture(
        family, exposure, procedure, "DRAFT — please remove ...", monkeypatch
    )

    assert "Maria Castillo" in calls[0]["user"]
    assert action.draft == "DRAFT — please remove ..."
    assert action.status == "drafted"


def test_draft_prompt_carries_no_child_or_contact_data(
    family: Family, exposure: Exposure, procedure, monkeypatch
):
    _, calls = _draft_and_capture(family, exposure, procedure, "draft", monkeypatch)

    prompt = calls[0]["user"]
    for forbidden in (
        "Sofia",
        "Lucas",
        "Lincoln Middle School",
        "Washington Elementary",
        "maria.castillo@example.com",
        "(217) 555-0142",
        "742 Evergreen Terrace",
    ):
        assert forbidden not in prompt


def test_draft_prompt_keeps_contact_details_as_placeholders(
    family: Family, exposure: Exposure, procedure, monkeypatch
):
    _, calls = _draft_and_capture(family, exposure, procedure, "draft", monkeypatch)

    prompt = calls[0]["user"]
    assert "[PHONE]" in prompt
    assert "[EMAIL]" in prompt


def test_draft_prompt_references_the_listing_and_the_procedure(
    family: Family, exposure: Exposure, procedure, monkeypatch
):
    _, calls = _draft_and_capture(family, exposure, procedure, "draft", monkeypatch)

    prompt = calls[0]["user"]
    assert exposure.source_url in prompt
    assert exposure.source_name in prompt
    assert "CCPA" in prompt
    assert "Government-issued ID" in prompt


def test_draft_model_failure_produces_a_marked_placeholder(
    family: Family, exposure: Exposure, procedure, monkeypatch
):
    action, _ = _draft_and_capture(
        family, exposure, procedure, RuntimeError("model down"), monkeypatch
    )

    assert "Draft generation failed" in action.draft
    assert action.status == "drafted"


def test_single_site_drafts_use_the_super_tier(
    family: Family, exposure: Exposure, procedure, monkeypatch
):
    action, calls = _draft_and_capture(family, exposure, procedure, "draft", monkeypatch)

    assert calls[0]["tier"] == "super"
    assert action.drafted_model == llm.TIER_MODELS["super"]


def test_single_exposure_batch_uses_super_tier(family: Family, monkeypatch):
    exposures = [make_exposure(exposure_id=f"e{i}") for i in range(3)]
    procedures = [make_procedure(e) for e in exposures]
    monkeypatch.setattr("haven.llm.complete", lambda **kw: "draft")

    actions = pipeline.draft_removal_requests(family, exposures, procedures)

    assert len(actions) == 3
    assert {a.drafted_model for a in actions} == {llm.TIER_MODELS["super"]}


def test_five_or_more_sites_escalate_to_the_ultra_tier(family: Family, monkeypatch):
    exposures = [make_exposure(exposure_id=f"e{i}") for i in range(5)]
    procedures = [make_procedure(e) for e in exposures]
    calls: list[dict[str, Any]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return "draft"

    monkeypatch.setattr("haven.llm.complete", fake)

    actions = pipeline.draft_removal_requests(family, exposures, procedures)

    assert len(actions) == 5
    assert {a.drafted_model for a in actions} == {llm.TIER_MODELS["ultra"]}
    assert {c["tier"] for c in calls} == {"ultra"}
    assert {c["purpose"] for c in calls} == {"draft_removal_multi_site"}


def test_exposures_without_a_procedure_are_skipped(family: Family, monkeypatch):
    exposures = [make_exposure(exposure_id="e0"), make_exposure(exposure_id="e1")]
    procedures = [make_procedure(exposures[0])]  # e1 has no procedure
    monkeypatch.setattr("haven.llm.complete", lambda **kw: "draft")

    actions = pipeline.draft_removal_requests(family, exposures, procedures)

    assert [a.exposure_id for a in actions] == ["e0"]


def test_drafts_are_never_auto_sent(family: Family, monkeypatch):
    """Every generated action starts in 'drafted', never 'sent'."""
    exposures = [make_exposure(exposure_id=f"e{i}") for i in range(5)]
    procedures = [make_procedure(e) for e in exposures]
    monkeypatch.setattr("haven.llm.complete", lambda **kw: "draft")

    actions = pipeline.draft_removal_requests(family, exposures, procedures)

    assert {a.status for a in actions} == {"drafted"}


# The end-to-end run_pipeline behaviour lives in tests/test_pipeline.py. This
# module covers the individual stages only.
