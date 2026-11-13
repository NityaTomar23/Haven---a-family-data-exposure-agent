"""Shared fixtures for the Haven test suite.

Design rules for this suite:

* No test may touch the network, and no API keys are required. Any test
  that needs Tavily or Nebius behaviour replaces it with a fake at the
  module attribute boundary (``haven.research.*`` / ``haven.llm.complete``).
* The ``no_network`` fixture is autouse, so an un-mocked call fails loudly
  instead of quietly spending a real API credit.
* LLM usage-log state, privacy gate state, and scan rate-limit history are
  reset between tests.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from haven.models import (  # noqa: E402
    Exposure,
    Family,
    Identifier,
    PipelineState,
    RemovalAction,
    RemovalProcedure,
)
from haven.seed import generate_family  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Make any real egress attempt fail the test instead of hitting the wire."""
    from haven import llm, offline, research

    monkeypatch.setenv("HAVEN_PROVIDER_MODE", "live")
    orig_llm_client = llm._get_client
    orig_research_client = research._get_client

    def _guard_llm(*args, **kwargs):
        if offline.provider_mode() == "offline":
            return orig_llm_client(*args, **kwargs)
        raise AssertionError(
            "test attempted a real network client; mock haven.llm.complete or "
            "haven.research.search_brokers/search_inventory/search_optout_procedure/extract_page"
        )

    def _guard_research(*args, **kwargs):
        if offline.provider_mode() == "offline":
            return orig_research_client(*args, **kwargs)
        raise AssertionError(
            "test attempted a real network client; mock haven.llm.complete or "
            "haven.research.search_brokers/search_inventory/search_optout_procedure/extract_page"
        )

    monkeypatch.setattr("haven.llm._get_client", _guard_llm)
    monkeypatch.setattr("haven.research._get_client", _guard_research)


@pytest.fixture(autouse=True)
def isolated_llm_state():
    """Reset the module-global tier usage log, OpenAI client, privacy gate, and rate limit."""
    from haven import api, llm, privacy

    llm.clear_usage_log()
    llm.reset_client()
    privacy.reset()
    api.reset_rate_limit()
    yield
    llm.clear_usage_log()
    llm.reset_client()
    privacy.reset()
    api.reset_rate_limit()


@pytest.fixture
def family() -> Family:
    """The deterministic synthetic adult demo family."""
    return generate_family()


@pytest.fixture
def exposure() -> Exposure:
    return make_exposure()


@pytest.fixture
def procedure(exposure: Exposure) -> RemovalProcedure:
    return make_procedure(exposure)


@pytest.fixture
def action(exposure: Exposure, procedure: RemovalProcedure) -> RemovalAction:
    return make_action(exposure, procedure)


@pytest.fixture
def state(family: Family) -> PipelineState:
    return PipelineState(family=family)


@pytest.fixture
def client(monkeypatch):
    """A TestClient over the real app, with the in-memory pipeline state reset."""
    from fastapi.testclient import TestClient

    from haven import api

    monkeypatch.setattr(api, "_state", None)
    api.reset_rate_limit()
    with TestClient(api.app) as test_client:
        yield test_client


# ── Builders (shared by several modules) ───────────────────────────────


def make_exposure(
    *,
    exposure_id: str = "exp00001",
    source_url: str = "https://spokeo.example/listing/avery-synthwell-ca",
    source_name: str = "Spokeo",
    broker_type: str = "people_search",
    confidence: float = 0.91,
    match_status: str = "verified",
) -> Exposure:
    return Exposure(
        id=exposure_id,
        source_url=source_url,
        source_name=source_name,
        broker_type=broker_type,  # type: ignore[arg-type]
        matched_identifiers=[
            Identifier(kind="name", value="Avery Synthwell", sensitivity="low"),
            Identifier(kind="city_state", value="Sampleville, CA", sensitivity="low"),
        ],
        confidence=confidence,
        evidence_snippet="Local exact match on [name, city_state] · stated location: Sampleville, CA",
        found_at=datetime.now(timezone.utc),
        match_status=match_status,  # type: ignore[arg-type]
        subject_member=0,
    )


def make_procedure(
    exposure: Exposure,
    *,
    method: str = "web_form",
    steps: list[str] | None = None,
) -> RemovalProcedure:
    now = datetime.now(timezone.utc)
    return RemovalProcedure(
        exposure_id=exposure.id,
        method=method,  # type: ignore[arg-type]
        action_url="https://spokeo.example/optout",
        required_evidence=["Listing URL", "Email address for confirmation"],
        statutory_deadline_days=45,
        deadline_source_url="https://oag.ca.gov/privacy/ccpa",
        deadline_verified_at=now,
        service_target_days=3,
        jurisdiction="CCPA",
        steps=steps or ["Open the opt-out form", "Submit the listing URL"],
        source_url="https://spokeo.example/optout",
        retrieved_at=now,
    )


def make_action(
    exposure: Exposure,
    procedure: RemovalProcedure,
    *,
    action_id: str = "act00001",
    status: str = "drafted",
    draft: str = "DRAFT — for human review only.\n\nPlease remove the listing at [LISTING_URL] for [FULL_NAME].",
) -> RemovalAction:
    now = datetime.now(timezone.utc)
    return RemovalAction(
        id=action_id,
        exposure_id=exposure.id,
        procedure=procedure,
        draft=draft,
        status=status,  # type: ignore[arg-type]
        drafted_model="nvidia/nemotron-3-super-120b-a12b",
        created_at=now,
        updated_at=now,
    )


def high_sensitivity_values(family: Family) -> list[str]:
    """Every identifier value marked high-sensitivity, for leak assertions."""
    return [
        ident.value
        for member in family.members
        for ident in member.identifiers
        if ident.sensitivity == "high"
    ]
