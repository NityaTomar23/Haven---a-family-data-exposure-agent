"""Validation contracts for the models the pipeline and dashboard depend on.

These lock the §5 shapes: if a field is loosened, a stage silently starts
accepting data the dashboard cannot render, so the bounds are asserted
explicitly rather than assumed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from haven.models import (
    EgressRecord,
    Exposure,
    Family,
    FamilyMember,
    Identifier,
    PipelineState,
    RemovalAction,
    RemovalProcedure,
    TierUsage,
)

NOW = datetime.now(timezone.utc)


def test_identifier_accepts_every_documented_kind():
    for kind in ("name", "phone", "email", "address", "city_state", "alias", "school"):
        ident = Identifier(kind=kind, value="x", sensitivity="low")
        assert ident.kind == kind


def test_identifier_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        Identifier(kind="ssn", value="123-45-6789", sensitivity="high")  # type: ignore[arg-type]


def test_identifier_rejects_unknown_sensitivity():
    """Sensitivity is a two-value switch; a typo must not default to 'low'."""
    with pytest.raises(ValidationError):
        Identifier(kind="name", value="Maria Castillo", sensitivity="medium")  # type: ignore[arg-type]


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0])
def test_exposure_confidence_is_bounded(confidence: float):
    with pytest.raises(ValidationError):
        Exposure(
            id="e1",
            source_url="https://example.test/a",
            source_name="Example",
            broker_type="people_search",
            matched_identifiers=[],
            confidence=confidence,
            evidence_snippet="snippet",
            found_at=NOW,
        )


def test_exposure_rejects_unknown_broker_type():
    with pytest.raises(ValidationError):
        Exposure(
            id="e1",
            source_url="https://example.test/a",
            source_name="Example",
            broker_type="spam",  # type: ignore[arg-type]
            matched_identifiers=[],
            confidence=0.5,
            evidence_snippet="snippet",
            found_at=NOW,
        )


def test_exposure_requires_a_timestamp():
    with pytest.raises(ValidationError):
        Exposure(
            id="e1",
            source_url="https://example.test/a",
            source_name="Example",
            broker_type="people_search",
            matched_identifiers=[],
            confidence=0.5,
            evidence_snippet="snippet",
        )  # type: ignore[call-arg]


def test_removal_procedure_nullable_fields_default_to_none():
    proc = RemovalProcedure(
        exposure_id="e1",
        method="manual_only",
        required_evidence=[],
        steps=["Do it by hand"],
        source_url="https://example.test/a",
    )
    assert proc.action_url is None
    assert proc.statutory_deadline_days is None
    assert proc.jurisdiction is None


def test_removal_procedure_rejects_unknown_method():
    with pytest.raises(ValidationError):
        RemovalProcedure(
            exposure_id="e1",
            method="carrier_pigeon",  # type: ignore[arg-type]
            required_evidence=[],
            steps=[],
            source_url="https://example.test/a",
        )


def test_removal_action_status_rejects_unknown_value(action: RemovalAction):
    payload = action.model_dump()
    payload["status"] = "done"
    with pytest.raises(ValidationError):
        RemovalAction(**payload)


def test_family_member_role_is_parent_or_child():
    with pytest.raises(ValidationError):
        FamilyMember(
            first_name="A",
            last_name="B",
            role="grandparent",  # type: ignore[arg-type]
            age=70,
            identifiers=[],
        )


def test_egress_decision_is_allowed_or_denied():
    with pytest.raises(ValidationError):
        EgressRecord(
            timestamp=NOW,
            destination_host="example.test",
            decision="maybe",  # type: ignore[arg-type]
            bytes_out=0,
            request_count=1,
        )


def test_tier_usage_tier_is_one_of_three_tiers():
    with pytest.raises(ValidationError):
        TierUsage(
            model="m",
            tier="mega",  # type: ignore[arg-type]
            input_tokens=0,
            output_tokens=0,
            latency_ms=1.0,
            purpose="test",
            timestamp=NOW,
        )


def test_pipeline_state_defaults_are_isolated_between_instances(family: Family):
    """Mutable defaults must not be shared across PipelineState instances."""
    first = PipelineState(family=family)
    second = PipelineState(family=family)

    first.exposures.append(
        Exposure(
            id="e1",
            source_url="https://example.test/a",
            source_name="Example",
            broker_type="other",
            matched_identifiers=[],
            confidence=0.4,
            evidence_snippet="s",
            found_at=NOW,
        )
    )

    assert len(second.exposures) == 0
    assert second.procedures == []
    assert second.actions == []
    assert second.egress_log == []
    assert second.tier_usage == []
