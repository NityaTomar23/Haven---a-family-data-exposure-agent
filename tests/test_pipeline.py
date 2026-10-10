"""The pipeline as a whole: ordering, wiring, and the tier ladder.

The stage-level behaviour lives in test_pipeline_discovery.py,
test_pipeline_procedures.py, test_pipeline_json.py and
test_pipeline_transitions.py. This module covers only what those cannot: that
run_pipeline wires the stages together in the right order, that tier escalation
and usage logging hold across a whole run, and that a run can never produce a
sent action.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from haven import llm, pipeline
from haven.models import Family, PipelineState, TierUsage


def _result(url: str, *, title: str = "Maria Castillo — Spokeo") -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "content": "Maria Castillo, Springfield IL",
    }


def _procedure_json() -> str:
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


class RunRecorder:
    """Replaces both providers and records what each stage asked for."""

    def __init__(self, *, search_results: list[dict[str, Any]], relevant: bool = True):
        self.search_results = search_results
        self.relevant = relevant
        self.search_queries: list[str] = []
        self.optout_sites: list[str] = []
        self.extract_urls: list[str] = []
        self.llm_purposes: list[str] = []

    def search_brokers(self, query: str, *, max_results: int = 10):
        self.search_queries.append(query)
        return self.search_results

    def search_optout_procedure(self, site_name: str):
        self.optout_sites.append(site_name)
        return [{"url": "https://spokeo.example/optout", "content": "opt out here"}]

    def extract_page(self, url: str):
        self.extract_urls.append(url)
        return {"raw_content": "Use the opt-out form."}

    def complete(self, **kwargs):
        self.llm_purposes.append(kwargs["purpose"])
        llm._usage_log.append(
            TierUsage(
                model=llm.model_for(kwargs["tier"]),
                tier=kwargs["tier"],
                input_tokens=100,
                output_tokens=50,
                latency_ms=12.5,
                purpose=kwargs["purpose"],
                timestamp=datetime.now(timezone.utc),
            )
        )
        if kwargs["purpose"] == "classify_search_result":
            return json.dumps(
                {
                    "relevant": self.relevant,
                    "confidence": 0.9,
                    "broker_type": "people_search",
                    "source_name": "Spokeo",
                    "evidence": "listing matches",
                }
            )
        if kwargs["purpose"] == "extract_optout_procedure":
            return _procedure_json()
        return "DRAFT — for human review only."


@pytest.fixture
def run(monkeypatch):
    """Install a recorder and return it; call it to execute a full run."""

    def _install(
        *,
        urls: list[str] | None = None,
        relevant: bool = True,
        relevance_threshold: float = 0.3,
    ) -> tuple[RunRecorder, PipelineState, Family]:
        recorder = RunRecorder(
            search_results=[
                _result(url)
                for url in (
                    ["https://spokeo.example/p/maria"] if urls is None else urls
                )
            ],
            relevant=relevant,
        )
        monkeypatch.setattr("haven.research.search_brokers", recorder.search_brokers)
        monkeypatch.setattr(
            "haven.research.search_optout_procedure", recorder.search_optout_procedure
        )
        monkeypatch.setattr("haven.research.extract_page", recorder.extract_page)
        monkeypatch.setattr("haven.llm.complete", recorder.complete)

        from haven.seed import generate_family

        family = generate_family()
        state = pipeline.run_pipeline(
            family, relevance_threshold=relevance_threshold
        )
        return recorder, state, family

    return _install


# ── Wiring ─────────────────────────────────────────────────────────────


def test_run_pipeline_returns_a_populated_state(run):
    recorder, state, family = run()

    assert state.family is family
    assert len(state.exposures) == 1
    assert len(state.procedures) == 1
    assert len(state.actions) == 1


def test_run_pipeline_executes_the_stages_in_order(run):
    """Discovery must precede procedures, which must precede drafting."""
    recorder, state, _ = run()

    assert recorder.search_queries, "discovery never ran"
    assert recorder.optout_sites, "procedure extraction never ran"
    assert recorder.extract_urls, "no opt-out page was read"

    # Every procedure lookup is for a site discovery actually found.
    assert set(recorder.optout_sites) <= {e.source_name for e in state.exposures}
    # Every draft belongs to an exposure that exists.
    exposure_ids = {e.id for e in state.exposures}
    assert {a.exposure_id for a in state.actions} <= exposure_ids


def test_procedures_are_extracted_once_per_discovered_exposure(run):
    recorder, state, _ = run(
        urls=[
            "https://spokeo.example/p/maria",
            "https://radaris.example/p/maria",
            "https://whitepages.example/p/maria",
        ]
    )

    assert len(state.exposures) == 3
    assert len(recorder.optout_sites) == 3
    assert len(state.procedures) == 3


def test_every_exposure_gets_a_draft(run):
    _, state, _ = run(
        urls=[
            "https://spokeo.example/p/maria",
            "https://radaris.example/p/maria",
            "https://whitepages.example/p/maria",
        ]
    )

    assert len(state.actions) == len(state.procedures) == len(state.exposures)


def test_run_pipeline_records_usage_for_every_model_call(run):
    recorder, state, _ = run()

    assert state.tier_usage
    assert len(state.tier_usage) == len(recorder.llm_purposes)
    assert {u.purpose for u in state.tier_usage} == set(recorder.llm_purposes)


def test_run_pipeline_uses_nano_for_classification_and_super_for_the_rest(run):
    _, state, _ = run()

    by_purpose = {u.purpose: u.tier for u in state.tier_usage}
    assert by_purpose["classify_search_result"] == "nano"
    assert by_purpose["extract_optout_procedure"] == "super"
    assert by_purpose["draft_removal_single"] == "super"


def test_many_sites_escalate_the_drafting_tier_across_a_whole_run(run):
    """The ultra escalation is a property of the run, not of one call."""
    urls = [f"https://broker{i}.example/p/maria" for i in range(5)]

    _, state, _ = run(urls=urls)

    assert len(state.exposures) == 5
    assert {a.drafted_model for a in state.actions} == {llm.model_for("ultra")}
    draft_tiers = {
        u.tier for u in state.tier_usage if u.purpose == "draft_removal_multi_site"
    }
    assert draft_tiers == {"ultra"}


def test_tier_usage_is_empty_when_nothing_is_found(run):
    _, state, _ = run(urls=[])
    assert state.tier_usage == []


# ── Degenerate runs ────────────────────────────────────────────────────


def test_a_run_with_no_search_results_still_returns_a_valid_state(run):
    _, state, family = run(urls=[])

    assert state.family is family
    assert state.exposures == []
    assert state.procedures == []
    assert state.actions == []
    assert state.egress_log == []


def test_an_irrelevant_result_set_produces_no_actions(run):
    _, state, _ = run(relevant=False)

    assert state.exposures == []
    assert state.actions == []


def test_the_relevance_threshold_is_applied_across_the_run(monkeypatch):
    """A threshold above the model's confidence suppresses every draft."""
    recorder = RunRecorder(search_results=[_result("https://spokeo.example/p/maria")])
    monkeypatch.setattr("haven.research.search_brokers", recorder.search_brokers)
    monkeypatch.setattr("haven.llm.complete", recorder.complete)

    from haven.seed import generate_family

    state = pipeline.run_pipeline(generate_family(), relevance_threshold=0.99)

    assert state.exposures == []
    assert state.actions == []


# ── The human gate ─────────────────────────────────────────────────────


def test_a_run_never_produces_a_sent_action(run):
    """No automated submission: a fresh run stops at 'drafted'."""
    _, state, _ = run(urls=[f"https://broker{i}.example/p/maria" for i in range(5)])

    assert state.actions
    assert {a.status for a in state.actions} == {"drafted"}


def test_drafts_record_the_model_that_produced_them(run):
    """The dashboard shows which tier drafted each request, so the recorded id
    must be the model actually called, not a hard-coded default."""
    _, state, _ = run()

    action = state.actions[0]
    assert action.drafted_model == llm.model_for("super")
    assert action.drafted_model in {usage.model for usage in state.tier_usage}


def test_the_run_is_repeatable_without_leaking_usage_between_calls(run):
    """The usage log is module-global, so a second run must not double-count."""
    _, first, _ = run()
    first_count = len(first.tier_usage)

    _, second, _ = run()

    assert len(second.tier_usage) == first_count
