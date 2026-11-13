"""Offline/simulated provider mode and fail-closed privacy enforcement."""

from __future__ import annotations

import pytest

from haven import llm, offline, pipeline, privacy, research


def test_provider_mode_auto_depends_on_api_keys(monkeypatch):
    monkeypatch.delenv("HAVEN_PROVIDER_MODE", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert offline.provider_mode() == "offline"

    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily")
    assert offline.provider_mode() == "live"

    monkeypatch.setenv("HAVEN_PROVIDER_MODE", "offline")
    assert offline.provider_mode() == "offline"

    monkeypatch.setenv("HAVEN_PROVIDER_MODE", "live")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    assert offline.provider_mode() == "live"


def test_offline_mode_runs_full_pipeline_and_marks_usage_simulated(family, monkeypatch):
    monkeypatch.setenv("HAVEN_PROVIDER_MODE", "offline")

    state = pipeline.run_pipeline(family)

    assert state.provider_mode == "offline"
    assert len(state.inventory) >= 4
    assert len(state.exposures) == 6
    assert len(state.procedures) == 5
    assert state.strategy is not None and len(state.strategy) > 0
    assert len(state.actions) == 5
    assert all(a.status == "drafted" for a in state.actions)

    usage = llm.get_usage_log()
    assert len(usage) > 0
    assert all(u.simulated is True for u in usage)
    assert {u.tier for u in usage} == {"nano", "super", "ultra"}


def test_offline_mode_still_enforces_outbound_privacy_gate(monkeypatch):
    monkeypatch.setenv("HAVEN_PROVIDER_MODE", "offline")

    with pytest.raises(privacy.PayloadBlocked):
        research.search_brokers("Avery Synthwell")

    with pytest.raises(privacy.PayloadBlocked):
        llm.complete(
            tier="super",
            system="You are drafting data removal requests.",
            user="Remove Avery Synthwell at 555-0142",
            purpose="draft_removal_request",
        )

