"""End-to-end pipeline wiring with all network boundaries mocked."""

from __future__ import annotations

import json

from haven import pipeline


def test_run_pipeline_wires_all_stages_and_all_three_tiers(family, monkeypatch):
    monkeypatch.setattr(
        "haven.research.search_inventory",
        lambda *, max_results=10: [
            {"url": "https://www.spokeo.com", "title": "Spokeo", "content": "People search site."},
            {
                "url": "https://www.whitepages.com",
                "title": "Whitepages",
                "content": "People search site.",
            },
        ],
    )
    monkeypatch.setattr(
        "haven.research.search_optout_procedure",
        lambda site: [{"url": f"https://{site.lower()}.example/optout", "content": "Opt out form."}],
    )
    monkeypatch.setattr(
        "haven.research.extract_page",
        lambda url: {"url": url, "raw_content": "Submit the listing URL to remove your record."},
    )

    tiers_called: list[str] = []

    def fake_complete(*, tier, system, user, purpose="unspecified", **kwargs):
        tiers_called.append(tier)
        if purpose == "classify_inventory_result":
            name = "Spokeo" if "Spokeo" in user else "Whitepages"
            return json.dumps(
                {
                    "is_broker": True,
                    "broker_name": name,
                    "broker_type": "people_search",
                    "confidence": 0.9,
                }
            )
        if purpose == "extract_optout_procedure":
            return json.dumps(
                {
                    "method": "web_form",
                    "action_url": "https://broker.example/optout",
                    "required_evidence": ["Listing URL"],
                    "statutory_deadline_days": 45,
                    "deadline_source_url": "https://oag.ca.gov/privacy/ccpa",
                    "service_target_days": 3,
                    "jurisdiction": "CCPA",
                    "steps": ["Open form", "Submit URL"],
                }
            )
        if purpose == "synthesize_removal_strategy":
            return "1. FastPeopleSearch (48h) -> 2. Spokeo -> 3. Whitepages"
        return "DRAFT template for [FULL_NAME] at [LISTING_URL] ([EMAIL], [PHONE], [ADDRESS])."

    monkeypatch.setattr("haven.llm.complete", fake_complete)

    state = pipeline.run_pipeline(family)

    assert len(state.inventory) == 2
    assert len(state.exposures) == 6  # 4 verified, 1 candidate, 1 rejected
    assert sum(1 for e in state.exposures if e.match_status == "verified") == 4
    assert sum(1 for e in state.exposures if e.match_status == "candidate") == 1
    assert sum(1 for e in state.exposures if e.match_status == "rejected") == 1
    assert len(state.procedures) == 5  # rejected skipped
    assert state.strategy is not None
    assert len(state.actions) == 5
    assert all(a.status == "drafted" for a in state.actions)
    assert set(tiers_called) == {"nano", "super", "ultra"}
